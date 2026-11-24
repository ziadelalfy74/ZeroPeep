import glob
import os
import cv2
import numpy as np
from deepface import DeepFace

try:
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    MEDIAPIPE_AVAILABLE = True
except Exception:
    MEDIAPIPE_AVAILABLE = False


class FaceGuard:
    def __init__(
        self,
        owner_faces_dir: str,
        model_path: str | None = None,
        camera_index: int = 0,
    ):
        self.owner_faces_dir = owner_faces_dir
        self.model_path = model_path
        self.camera_index = camera_index
        self.model_name = "SFace"
        self.detector_backend = "opencv"
        self.last_filter_mode = "Waiting..."

        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.smile_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_smile.xml"
        )

        self.landmarker = None
        if (
            MEDIAPIPE_AVAILABLE
            and self.model_path
            and os.path.exists(self.model_path)
        ):
            try:
                base_options = mp_python.BaseOptions(model_asset_path=self.model_path)
                options = mp_vision.FaceLandmarkerOptions(
                    base_options=base_options,
                    output_face_blendshapes=True,
                    num_faces=1,
                )
                self.landmarker = mp_vision.FaceLandmarker.create_from_options(options)
            except Exception:
                self.landmarker = None

        os.makedirs(self.owner_faces_dir, exist_ok=True)

    def get_saved_samples(self) -> list[str]:
        patterns = ["*.jpg", "*.jpeg", "*.png"]
        files = []
        for p in patterns:
            files.extend(glob.glob(os.path.join(self.owner_faces_dir, p)))
        return sorted(files)

    @property
    def owner_ready(self) -> bool:
        return len(self.get_saved_samples()) > 0

    def clear_saved_samples(self) -> None:
        for old_file in self.get_saved_samples():
            try:
                os.remove(old_file)
            except OSError:
                pass

    def _open_camera(self) -> cv2.VideoCapture | None:
        try:
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                return None
            return cap
        except Exception:
            return None

    def _adjust_gamma(self, bgr_frame: np.ndarray, gamma: float) -> np.ndarray:
        inv_gamma = 1.0 / max(gamma, 0.1)
        table = np.array(
            [((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]
        ).astype("uint8")
        return cv2.LUT(bgr_frame, table)

    def smart_filter(self, bgr_frame: np.ndarray) -> tuple[np.ndarray, str]:
        """فلتر ذكي متكيّف يوازن الإضاءة والتباين تلقائياً"""
        lab = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        mean_l = float(np.mean(l_channel))

        if mean_l < 75.0:
            gamma = float(np.clip(75.0 / max(mean_l, 15.0), 1.15, 2.0))
            gamma_applied = self._adjust_gamma(bgr_frame, gamma)
            g_lab = cv2.cvtColor(gamma_applied, cv2.COLOR_BGR2LAB)
            gl, ga, gb = cv2.split(g_lab)
            clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
            gl = clahe.apply(gl)
            filtered = cv2.cvtColor(cv2.merge((gl, ga, gb)), cv2.COLOR_LAB2BGR)
            mode = f"Low-Light Boost (γ={gamma:.2f})"
        elif mean_l > 175.0:
            gamma = float(np.clip(175.0 / mean_l, 0.65, 0.92))
            gamma_applied = self._adjust_gamma(bgr_frame, gamma)
            g_lab = cv2.cvtColor(gamma_applied, cv2.COLOR_BGR2LAB)
            gl, ga, gb = cv2.split(g_lab)
            clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
            gl = clahe.apply(gl)
            filtered = cv2.cvtColor(cv2.merge((gl, ga, gb)), cv2.COLOR_LAB2BGR)
            mode = f"Bright-Light Balance (γ={gamma:.2f})"
        else:
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
            cl = clahe.apply(l_channel)
            filtered = cv2.cvtColor(cv2.merge((cl, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
            mode = "Balanced Smart CLAHE"

        filtered = cv2.bilateralFilter(filtered, d=5, sigmaColor=20, sigmaSpace=20)
        self.last_filter_mode = mode
        return filtered, mode

    def analyze_landmarks(self, frame: np.ndarray) -> dict | None:
        """
        يرجع بيانات الوجه والنقاط المرجعية:
        box: (x, y, w, h)
        nose: (nx, ny) بالبكسل
        smile_score: قيمة بين 0 و 1
        """
        h, w = frame.shape[:2]

        if self.landmarker is not None:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                res = self.landmarker.detect(mp_image)
                if res.face_landmarks:
                    lms = res.face_landmarks[0]
                    xs = [p.x * w for p in lms]
                    ys = [p.y * h for p in lms]
                    x1, x2 = max(0, int(min(xs))), min(w, int(max(xs)))
                    y1, y2 = max(0, int(min(ys))), min(h, int(max(ys)))
                    bw, bh = max(1, x2 - x1), max(1, y2 - y1)

                    nose_pt = lms[1]
                    nx, ny = float(nose_pt.x * w), float(nose_pt.y * h)

                    mouth_l = np.array([lms[61].x * w, lms[61].y * h])
                    mouth_r = np.array([lms[291].x * w, lms[291].y * h])
                    mouth_t = np.array([lms[13].x * w, lms[13].y * h])
                    mouth_b = np.array([lms[14].x * w, lms[14].y * h])

                    m_width = float(np.linalg.norm(mouth_r - mouth_l))
                    m_height = max(1.0, float(np.linalg.norm(mouth_b - mouth_t)))
                    smile_ratio = m_width / max(bw * 0.35, 1.0)
                    open_ratio = m_height / max(m_width, 1.0)

                    blend_smile = 0.0
                    if res.face_blendshapes:
                        for cat in res.face_blendshapes[0]:
                            if cat.category_name in ("mouthSmileLeft", "mouthSmileRight"):
                                blend_smile = max(blend_smile, float(cat.score))

                    smile_score = max(
                        blend_smile,
                        min(1.0, max(0.0, (smile_ratio - 1.05) * 1.4 + open_ratio * 0.8)),
                    )

                    return {
                        "box": (x1, y1, bw, bh),
                        "nose": (nx, ny),
                        "smile_score": smile_score,
                        "engine": "FaceLandmarker",
                    }
            except Exception:
                pass

        # Fallback بـ OpenCV لو احتجت
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.12, minNeighbors=3, minSize=(65, 65)
        )
        if len(faces) == 0:
            return None

        x, y, bw, bh = max(faces, key=lambda b: b[2] * b[3])
        nx, ny = float(x + bw * 0.5), float(y + bh * 0.5)

        lower = gray[y + int(bh * 0.45) : min(h, y + bh), x : min(w, x + bw)]
        smile_score = 0.0
        if lower.size > 0:
            smiles = self.smile_cascade.detectMultiScale(
                lower, scaleFactor=1.25, minNeighbors=7, minSize=(16, 12)
            )
            if len(smiles) > 0:
                smile_score = 0.8

        return {
            "box": (int(x), int(y), int(bw), int(bh)),
            "nose": (nx, ny),
            "smile_score": smile_score,
            "engine": "OpenCV",
        }

    def check_challenge(
        self,
        frame: np.ndarray,
        info: dict | None,
        challenge: str,
        baseline_nose: tuple[float, float] | None,
    ) -> tuple[bool, str]:
        if info is None:
            return False, "No face detected — keep your face in view"

        x, y, w, h = info["box"]
        nx, ny = info["nose"]
        smile_score = info["smile_score"]
        frame_h, frame_w = frame.shape[:2]

        if challenge == "center":
            ok_x = abs(nx - frame_w * 0.5) < frame_w * 0.24
            ok_y = abs(ny - frame_h * 0.5) < frame_h * 0.24
            if ok_x and ok_y:
                return True, f"Center verified ({info['engine']})"
            return False, "Look straight at the center of the camera"

        if baseline_nose is None:
            return False, "Calibrating center reference..."

        bx, by = baseline_nose
        dx = nx - bx
        dy = ny - by

        req_x = max(14.0, w * 0.08)
        req_y = max(12.0, h * 0.07)

        if challenge == "right":
            if dx >= req_x:
                return True, f"RIGHT verified (+{int(dx)}px)"
            return False, f"Turn/move RIGHT (need +{int(req_x)}px, now {int(dx)}px)"

        if challenge == "left":
            if dx <= -req_x:
                return True, f"LEFT verified ({int(dx)}px)"
            return False, f"Turn/move LEFT (need -{int(req_x)}px, now {int(dx)}px)"

        if challenge == "up":
            if dy <= -req_y:
                return True, f"UP verified ({int(dy)}px)"
            return False, f"Tilt/look UP (need -{int(req_y)}px, now {int(dy)}px)"

        if challenge == "down":
            if dy >= req_y:
                return True, f"DOWN verified (+{int(dy)}px)"
            return False, f"Tilt/look DOWN (need +{int(req_y)}px, now {int(dy)}px)"

        if challenge == "smile":
            if smile_score >= 0.42:
                return True, f"Smile verified ({smile_score:.2f})"
            return False, f"Smile clearly at camera (score: {smile_score:.2f})"

        return False, "Unknown challenge"

    def save_filtered_sample(self, filtered_frame: np.ndarray, index: int) -> str:
        save_path = os.path.join(self.owner_faces_dir, f"face_{index:02d}.jpg")
        cv2.imwrite(save_path, filtered_frame)
        return save_path

    def _has_real_face(self, frame: np.ndarray) -> bool:
        """يتحقق أولاً بوجود وجه فعلي في الفريم قبل المقارنة"""
        if self.landmarker is not None:
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                res = self.landmarker.detect(mp_image)
                if res.face_landmarks and len(res.face_landmarks) > 0:
                    return True
            except Exception:
                pass

        try:
            faces = DeepFace.extract_faces(
                img_path=frame,
                detector_backend=self.detector_backend,
                enforce_detection=True,
            )
            return len(faces) > 0
        except Exception:
            return False
    #لو فيه اي مشكله هنا الترموستات الي بعلي و اوطي بيها التمبرتشر بتاعت النموزج 
    def is_owner_present(self, threshold: float = 0.52) -> bool:
        samples = self.get_saved_samples()
        if not samples:
            self.last_filter_mode = "No Samples"
            return False

        cap = self._open_camera()
        if cap is None:
            self.last_filter_mode = "Camera Offline"
            return False

        frame = None
        try:
            for _ in range(4):
                ret, temp = cap.read()
                if ret and temp is not None and temp.size > 0:
                    frame = temp
        except Exception:
            frame = None
        finally:
            try:
                cap.release()
            except Exception:
                pass

        if frame is None:
            self.last_filter_mode = "No Frame"
            return False

        filtered_frame, mode = self.smart_filter(frame)
        self.last_filter_mode = mode

        if not (self._has_real_face(filtered_frame) or self._has_real_face(frame)):
            return False

        # مقارنة ضد جميع العينات المحفوظة بعتبة منخفضة
        for img_variant in (filtered_frame, frame):
            for sample_path in samples:
                try:
                    result = DeepFace.verify(
                        img1_path=img_variant,
                        img2_path=sample_path,
                        model_name=self.model_name,
                        detector_backend=self.detector_backend,
                        distance_metric="cosine",
                        enforce_detection=False,
                    )
                    distance = float(result.get("distance", 1.0))
                    if distance <= threshold:
                        return True
                except Exception:
                    continue

        return False