import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog
import cv2
from PIL import Image, ImageTk


def _resource_path(filename: str) -> str:
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, filename)


ICON_PATH = _resource_path("zeropeep.ico")

from config import (
    ABSENCE_LOCK_SEC,
    AUTO_UNLOCK_ON_RETURN,
    CAMERA_INDEX,
    CHECK_INTERVAL_SEC,
    FACE_LANDMARKER_MODEL_PATH,
    OWNER_FACES_DIR,
    PASSWORD_HASH_FILE,
    save_password,
    verify_password,
)
from face_guard import FaceGuard


CHALLENGES = [
    ("center", "1/6: Look straight at the camera"),
    ("right", "2/6: Look / move slightly RIGHT"),
    ("left", "3/6: Look / move slightly LEFT"),
    ("up", "4/6: Tilt / look slightly UP"),
    ("down", "5/6: Tilt / look slightly DOWN"),
    ("smile", "6/6: SMILE at the camera"),
]


class SmartPresenceLockApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ZeroPeep — Smart Presence Lock")
        self.root.geometry("620x430")
        self.root.minsize(580, 410)

        self.bg_main = "#0B0F17"
        self.bg_card = "#131A26"
        self.bg_card_alt = "#192232"
        self.border_col = "#243044"
        self.text_main = "#F1F5F9"
        self.text_muted = "#94A3B8"
        self.accent_green = "#10B981"
        self.accent_amber = "#F59E0B"
        self.accent_red = "#EF4444"
        self.accent_blue = "#3B82F6"

        self.root.configure(bg=self.bg_main)
        self._apply_icon(self.root)

        self.guard = FaceGuard(
            OWNER_FACES_DIR,
            model_path=FACE_LANDMARKER_MODEL_PATH,
            camera_index=CAMERA_INDEX,
        )
        self.running = True
        self.locked = False
        self.absence_elapsed = 0.0
        self.lock_window = None
        self.scan_active = False

        total_steps = len(CHALLENGES)
        self.auto_unlock_var = tk.BooleanVar(value=AUTO_UNLOCK_ON_RETURN)
        self.status_var = tk.StringVar(value="INITIALIZING...")
        self.substatus_var = tk.StringVar(value="Preparing camera & smart lighting filter")
        self.filter_var = tk.StringVar(value="Filter: —")
        self.timer_var = tk.StringVar(value=f"0.0s / {ABSENCE_LOCK_SEC:.1f}s away")
        self.samples_var = tk.StringVar(value=f"{len(self.guard.get_saved_samples())} / {total_steps}")

        self._initial_setup()
        if not self.running:
            return

        self._build_ui()

        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def _apply_icon(self, window: tk.Misc):
        if not os.path.exists(ICON_PATH):
            return
        try:
            window.iconbitmap(ICON_PATH)
        except Exception:
            try:
                pil_icon = Image.open(ICON_PATH)
                tk_icon = ImageTk.PhotoImage(pil_icon)
                if not hasattr(self, "_icon_refs"):
                    self._icon_refs = []
                self._icon_refs.append(tk_icon)
                window.iconphoto(False, tk_icon)
            except Exception:
                pass

    def _initial_setup(self):
        if not os.path.exists(PASSWORD_HASH_FILE):
            pwd = simpledialog.askstring(
                "Password Setup",
                "Enter a password to unlock the blackout screen:",
                show="*",
                parent=self.root,
            )
            if not pwd:
                messagebox.showwarning("Required", "A password is required to continue.")
                self.running = False
                self.root.destroy()
                return
            save_password(pwd)

        if not self.guard.owner_ready:
            self.root.after(150, self.open_challenge_scan_modal)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=self.bg_main)
        header.pack(fill="x", padx=24, pady=(20, 10))

        tk.Label(
            header,
            text="AEGISVISION",
            font=("Segoe UI", 18, "bold"),
            fg=self.text_main,
            bg=self.bg_main,
        ).pack(anchor="w")

        tk.Label(
            header,
            text="Adaptive Presence Guard & Blackout Screen Controller",
            font=("Segoe UI", 10),
            fg=self.text_muted,
            bg=self.bg_main,
        ).pack(anchor="w", pady=(2, 0))

        status_card = tk.Frame(
            self.root,
            bg=self.bg_card,
            highlightbackground=self.border_col,
            highlightthickness=1,
        )
        status_card.pack(fill="x", padx=24, pady=8)

        top_row = tk.Frame(status_card, bg=self.bg_card)
        top_row.pack(fill="x", padx=18, pady=(14, 4))

        self.dot_canvas = tk.Canvas(
            top_row, width=14, height=14, bg=self.bg_card, highlightthickness=0
        )
        self.dot_canvas.pack(side="left", padx=(0, 10), pady=2)
        self.dot_id = self.dot_canvas.create_oval(2, 2, 12, 12, fill=self.accent_amber, outline="")

        self.status_lbl = tk.Label(
            top_row,
            textvariable=self.status_var,
            font=("Segoe UI", 13, "bold"),
            fg=self.text_main,
            bg=self.bg_card,
        )
        self.status_lbl.pack(side="left")

        tk.Label(
            status_card,
            textvariable=self.substatus_var,
            font=("Segoe UI", 10),
            fg=self.text_muted,
            bg=self.bg_card,
        ).pack(anchor="w", padx=42, pady=(0, 12))

        stats_grid = tk.Frame(self.root, bg=self.bg_main)
        stats_grid.pack(fill="x", padx=24, pady=6)
        stats_grid.columnconfigure((0, 1, 2), weight=1, uniform="stats")

        self._make_stat_box(stats_grid, 0, "FACE SAMPLES", self.samples_var, self.accent_blue)
        self._make_stat_box(stats_grid, 1, "SMART FILTER", self.filter_var, self.accent_green)
        self._make_stat_box(stats_grid, 2, "ABSENCE TIMER", self.timer_var, self.accent_amber)

        opts_card = tk.Frame(
            self.root,
            bg=self.bg_card,
            highlightbackground=self.border_col,
            highlightthickness=1,
        )
        opts_card.pack(fill="x", padx=24, pady=8)

        tk.Checkbutton(
            opts_card,
            text="Auto-unlock blackout screen when owner returns",
            variable=self.auto_unlock_var,
            font=("Segoe UI", 10),
            fg=self.text_main,
            bg=self.bg_card,
            selectcolor=self.bg_card_alt,
            activebackground=self.bg_card,
            activeforeground=self.text_main,
            highlightthickness=0,
            bd=0,
        ).pack(anchor="w", padx=16, pady=12)

        actions_top = tk.Frame(self.root, bg=self.bg_main)
        actions_top.pack(fill="x", padx=24, pady=(10, 8))

        tk.Button(
            actions_top,
            text="Lock Now",
            command=lambda: self.root.after(0, self.lock_screen),
            font=("Segoe UI", 10, "bold"),
            bg=self.accent_blue,
            fg="#FFFFFF",
            activebackground="#2563EB",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=18,
            pady=8,
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            actions_top,
            text="Exit",
            command=self._quit_app,
            font=("Segoe UI", 10, "bold"),
            bg="#2A1418",
            fg="#FCA5A5",
            activebackground="#3F1A20",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
        ).pack(side="right")

        actions_bottom = tk.Frame(self.root, bg=self.bg_main)
        actions_bottom.pack(fill="x", padx=24, pady=(0, 18))

        tk.Button(
            actions_bottom,
            text="Guided Scan (6 Steps)",
            command=self.open_challenge_scan_modal,
            font=("Segoe UI", 10, "bold"),
            bg=self.bg_card_alt,
            fg=self.text_main,
            activebackground="#233046",
            activeforeground=self.text_main,
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=(0, 12))

        tk.Button(
            actions_bottom,
            text="Change Password",
            command=self.open_change_password_modal,
            font=("Segoe UI", 10, "bold"),
            bg=self.bg_card_alt,
            fg=self.text_main,
            activebackground="#233046",
            activeforeground=self.text_main,
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
        ).pack(side="left")
    
    def open_change_password_modal(self):
        has_existing = os.path.exists(PASSWORD_HASH_FILE)
        owner_verified = "OWNER VERIFIED" in self.status_var.get().upper()

        if not has_existing and self.guard.owner_ready and not owner_verified:
            messagebox.showwarning(
                "Permission Required",
                "Please verify owner presence first before setting a password.",
                parent=self.root,
            )
            return

        win = tk.Toplevel(self.root)
        win.title("Change Password")
        win.configure(bg=self.bg_main)
        win.geometry("400x340" if has_existing else "400x285")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        tk.Label(
            win,
            text="Change Password",
            font=("Segoe UI", 14, "bold"),
            fg=self.text_main,
            bg=self.bg_main,
        ).pack(anchor="w", padx=24, pady=(20, 4))

        tk.Label(
            win,
            text="Update unlock password for blackout screen",
            font=("Segoe UI", 9),
            fg=self.text_muted,
            bg=self.bg_main,
        ).pack(anchor="w", padx=24, pady=(0, 14))

        def build_field(label: str) -> tk.Entry:
            tk.Label(
                win,
                text=label,
                font=("Segoe UI", 9),
                fg=self.text_muted,
                bg=self.bg_main,
            ).pack(anchor="w", padx=24, pady=(4, 2))

            ent = tk.Entry(
                win,
                show="•",
                font=("Segoe UI", 10),
                bg=self.bg_card,
                fg=self.text_main,
                insertbackground=self.text_main,
                relief="flat",
                highlightbackground=self.border_col,
                highlightthickness=1,
            )
            ent.pack(fill="x", padx=24, ipady=6, pady=(0, 6))
            return ent

        curr_entry = build_field("Current Password") if has_existing else None
        new_entry = build_field("New Password")
        confirm_entry = build_field("Confirm Password")

        def on_save():
            new_pw = new_entry.get().strip()
            confirm_pw = confirm_entry.get().strip()

            if has_existing:
                curr_pw = curr_entry.get().strip()
                owner_now = "OWNER VERIFIED" in self.status_var.get().upper()
                if not verify_password(curr_pw) and not owner_now:
                    messagebox.showerror(
                        "Invalid Credentials",
                        "Current password is incorrect and owner is not verified.",
                        parent=win,
                    )
                    return

            if not new_pw:
                messagebox.showwarning(
                    "Empty Password",
                    "New password cannot be empty.",
                    parent=win,
                )
                return

            if new_pw != confirm_pw:
                messagebox.showerror(
                    "Mismatch",
                    "New password and confirmation do not match.",
                    parent=win,
                )
                return

            save_password(new_pw)
            win.grab_release()
            win.destroy()
            self.substatus_var.set("Unlock password updated.")
            messagebox.showinfo("Done", "Password updated successfully.", parent=self.root)

        btns = tk.Frame(win, bg=self.bg_main)
        btns.pack(fill="x", padx=24, pady=(12, 16))

        tk.Button(
            btns,
            text="Save",
            command=on_save,
            font=("Segoe UI", 10, "bold"),
            bg=self.accent_blue,
            fg="#FFFFFF",
            activebackground="#2563EB",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=18,
            pady=7,
            cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btns,
            text="Cancel",
            command=lambda: (win.grab_release(), win.destroy()),
            font=("Segoe UI", 10, "bold"),
            bg=self.bg_card_alt,
            fg=self.text_main,
            activebackground="#233046",
            activeforeground=self.text_main,
            relief="flat",
            padx=16,
            pady=7,
            cursor="hand2",
        ).pack(side="right")

        win.protocol("WM_DELETE_WINDOW", lambda: (win.grab_release(), win.destroy()))


    def _make_stat_box(self, parent, col: int, title: str, var: tk.StringVar, accent: str):
        box = tk.Frame(
            parent,
            bg=self.bg_card,
            highlightbackground=self.border_col,
            highlightthickness=1,
        )
        padx_val = (0, 6) if col == 0 else ((6, 6) if col == 1 else (6, 0))
        box.grid(row=0, column=col, sticky="nsew", padx=padx_val)

        tk.Label(
            box,
            text=title,
            font=("Segoe UI", 8, "bold"),
            fg=accent,
            bg=self.bg_card,
        ).pack(anchor="w", padx=12, pady=(10, 2))

        tk.Label(
            box,
            textvariable=var,
            font=("Segoe UI", 10, "bold"),
            fg=self.text_main,
            bg=self.bg_card,
            wraplength=165,
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 10))
    
    

    def _set_indicator(self, color: str):
        self.dot_canvas.itemconfig(self.dot_id, fill=color)

    def open_challenge_scan_modal(self):
        if self.scan_active:
            return

        existing_samples = self.guard.get_saved_samples()
        if len(existing_samples) > 0:
            retry = messagebox.askyesno(
                "إعادة الاسكان",
                "الاسكان تمام، هل أنت عايز إعادة؟",
                parent=self.root,
            )
            if not retry:
                return

        self.scan_active = True

        if hasattr(self.guard, "camera_lock"):
            wait_start = time.time()
            while self.guard.camera_lock.locked() and (time.time() - wait_start < 1.5):
                time.sleep(0.05)

        modal = tk.Toplevel(self.root)
        modal.title("Verified Action Face Scan")
        modal.configure(bg=self.bg_main)
        modal.geometry("620x580")
        modal.transient(self.root)
        modal.grab_set()

        step_idx = 0
        baseline_nose = None
        hold_verified_since = None
        latest_filtered = {"img": None, "info": None}
        photo_holder = {"img": None}
        cap_holder = {"cap": None, "lock_acquired": False}

        _, challenge_text = CHALLENGES[0]

        step_lbl = tk.Label(
            modal,
            text=challenge_text,
            font=("Segoe UI", 13, "bold"),
            fg=self.accent_green,
            bg=self.bg_main,
        )
        step_lbl.pack(pady=(14, 4))

        feedback_lbl = tk.Label(
            modal,
            text="Starting camera...",
            font=("Segoe UI", 10),
            fg=self.accent_amber,
            bg=self.bg_main,
        )
        feedback_lbl.pack(pady=(0, 8))

        canvas_w, canvas_h = 540, 360
        cam_canvas = tk.Canvas(
            modal,
            width=canvas_w,
            height=canvas_h,
            bg="#111827",
            highlightbackground=self.border_col,
            highlightthickness=1,
        )
        cam_canvas.pack(pady=4)
        canvas_img_id = cam_canvas.create_image(0, 0, anchor="nw")

        filter_lbl = tk.Label(
            modal,
            text="Smart Filter: —",
            font=("Segoe UI", 9),
            fg=self.text_muted,
            bg=self.bg_main,
        )
        filter_lbl.pack(pady=(6, 4))

        def advance_step(filtered_img, landmark_info):
            nonlocal step_idx, baseline_nose, hold_verified_since
            if filtered_img is not None:
                self.guard.save_filtered_sample(filtered_img, step_idx + 1)
                if landmark_info is not None and baseline_nose is None:
                    baseline_nose = landmark_info["nose"]

            step_idx += 1
            hold_verified_since = None

            if step_idx >= len(CHALLENGES):
                close_scan("All 6 action challenges verified and saved!")
                return True

            _, next_prompt = CHALLENGES[step_idx]
            step_lbl.config(text=next_prompt)
            return False

        def close_scan(finished_msg: str | None = None):
            self.scan_active = False
            cap_obj = cap_holder["cap"]
            cap_holder["cap"] = None
            try:
                if cap_obj is not None and cap_obj.isOpened():
                    cap_obj.release()
            except Exception:
                pass
            time.sleep(0.12)
            if cap_holder["lock_acquired"] and hasattr(self.guard, "camera_lock"):
                cap_holder["lock_acquired"] = False
                try:
                    self.guard.camera_lock.release()
                except RuntimeError:
                    pass
            try:
                modal.grab_release()
            except Exception:
                pass
            try:
                modal.destroy()
            except tk.TclError:
                pass
            self.samples_var.set(f"{len(self.guard.get_saved_samples())} / {len(CHALLENGES)}")
            if finished_msg:
                self.substatus_var.set(finished_msg)

        btn_bar = tk.Frame(modal, bg=self.bg_main)
        btn_bar.pack(pady=8)

        tk.Button(
            btn_bar,
            text="Confirm Step",
            command=lambda: advance_step(latest_filtered["img"], latest_filtered["info"]),
            font=("Segoe UI", 10, "bold"),
            bg=self.accent_blue,
            fg="#FFFFFF",
            relief="flat",
            padx=16,
            pady=7,
            cursor="hand2",
        ).pack(side="left", padx=8)

        tk.Button(
            btn_bar,
            text="Cancel Scan",
            command=lambda: close_scan("Scan cancelled."),
            font=("Segoe UI", 10, "bold"),
            bg=self.bg_card_alt,
            fg=self.text_main,
            relief="flat",
            padx=16,
            pady=7,
            cursor="hand2",
        ).pack(side="left", padx=8)

        modal.protocol("WM_DELETE_WINDOW", lambda: close_scan("Scan cancelled."))

        def update_frame():
            nonlocal hold_verified_since
            if not self.scan_active or not modal.winfo_exists():
                return

            cap_obj = cap_holder["cap"]
            if cap_obj is None:
                modal.after(40, update_frame)
                return

            try:
                ret, frame = cap_obj.read()
            except Exception:
                ret, frame = False, None

            if ret and frame is not None and frame.size > 0:
                filtered, mode = self.guard.smart_filter(frame)
                filter_lbl.config(text=f"Smart Filter: {mode}")

                info = self.guard.analyze_landmarks(filtered)
                latest_filtered["img"] = filtered
                latest_filtered["info"] = info

                vis = filtered.copy()
                if info is not None:
                    x, y, w, h = info["box"]
                    nx, ny = info["nose"]
                    cv2.rectangle(vis, (x, y), (x + w, y + h), (16, 185, 129), 2)
                    cv2.circle(vis, (int(nx), int(ny)), 5, (59, 130, 246), -1)

                curr_key, _ = CHALLENGES[step_idx]
                passed, reason = self.guard.check_challenge(
                    filtered, info, curr_key, baseline_nose
                )

                now = time.time()
                if passed:
                    feedback_lbl.config(text=reason, fg=self.accent_green)
                    if hold_verified_since is None:
                        hold_verified_since = now
                    elif (now - hold_verified_since) >= 0.35:
                        if advance_step(filtered, info):
                            return
                else:
                    hold_verified_since = None
                    feedback_lbl.config(text=reason, fg=self.accent_amber)

                rgb = cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)
                src_h, src_w = rgb.shape[:2]
                scale = min(canvas_w / src_w, canvas_h / src_h)
                new_w = max(1, int(src_w * scale))
                new_h = max(1, int(src_h * scale))
                resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)

                padded = Image.new("RGB", (canvas_w, canvas_h), (17, 24, 39))
                pil_img = Image.fromarray(resized)
                offset_x = (canvas_w - new_w) // 2
                offset_y = (canvas_h - new_h) // 2
                padded.paste(pil_img, (offset_x, offset_y))

                tk_img = ImageTk.PhotoImage(image=padded)
                photo_holder["img"] = tk_img
                cam_canvas.itemconfig(canvas_img_id, image=tk_img)
            else:
                feedback_lbl.config(text="Reading camera stream...", fg=self.accent_amber)

            modal.after(35, update_frame)

        def init_scan_camera():
            if not self.scan_active or not modal.winfo_exists():
                return
            if hasattr(self.guard, "camera_lock"):
                self.guard.camera_lock.acquire()
                cap_holder["lock_acquired"] = True

            self.guard.clear_saved_samples()

            if hasattr(self.guard, "_open_camera"):
                cap_obj = self.guard._open_camera()
            else:
                cap_obj = cv2.VideoCapture(self.guard.camera_index, cv2.CAP_DSHOW)
                if not cap_obj.isOpened():
                    cap_obj = cv2.VideoCapture(self.guard.camera_index)
                if not cap_obj.isOpened():
                    cap_obj = None

            if cap_obj is None:
                close_scan()
                messagebox.showerror("Camera Error", "Could not open camera.", parent=self.root)
                return

            cap_holder["cap"] = cap_obj
            update_frame()

        modal.after(80, init_scan_camera)


    def _monitor_loop(self):
        while self.running:
            time.sleep(CHECK_INTERVAL_SEC)
            if not self.running:
                break
            if self.scan_active:
                continue

            try:
                present = self.guard.is_owner_present()
            except Exception:
                present = False

            filter_label = self.guard.last_filter_mode

            if present:
                self.absence_elapsed = 0.0
                self.root.after(
                    0,
                    lambda f=filter_label: (
                        self._set_indicator(self.accent_green),
                        self.status_var.set("OWNER VERIFIED"),
                        self.substatus_var.set("Presence confirmed — screen unlocked"),
                        self.filter_var.set(f),
                        self.timer_var.set(f"0.0s / {ABSENCE_LOCK_SEC:.1f}s away"),
                    ),
                )
                if self.locked and self.auto_unlock_var.get():
                    self.root.after(0, self.unlock_screen)
            else:
                self.absence_elapsed += CHECK_INTERVAL_SEC
                remaining = max(0.0, ABSENCE_LOCK_SEC - self.absence_elapsed)
                self.root.after(
                    0,
                    lambda f=filter_label, r=remaining, e=self.absence_elapsed: (
                        self._set_indicator(self.accent_red if self.locked else self.accent_amber),
                        self.status_var.set("SCREEN LOCKED" if self.locked else "OWNER NOT DETECTED"),
                        self.substatus_var.set(
                            "Blackout active — enter password or return"
                            if self.locked
                            else f"Locking in {r:.1f}s of continuous absence"
                        ),
                        self.filter_var.set(f),
                        self.timer_var.set(f"{e:.1f}s / {ABSENCE_LOCK_SEC:.1f}s away"),
                    ),
                )
                if self.absence_elapsed >= ABSENCE_LOCK_SEC and not self.locked:
                    self.root.after(0, self.lock_screen)

    def lock_screen(self):
        if self.locked:
            return
        self.locked = True
        self._set_indicator(self.accent_red)
        self.status_var.set("SCREEN LOCKED")
        self.substatus_var.set("Blackout overlay active")

        win = tk.Toplevel(self.root)
        self.lock_window = win
        win.configure(bg="#05070B")
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        
        panel = tk.Frame(
            win,
            bg="#0E131D",
            highlightbackground="#1E293B",
            highlightthickness=1,
        )
        panel.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(
            panel,
            text="SCREEN LOCKED",
            font=("Segoe UI", 26, "bold"),
            fg="#F8FAFC",
            bg="#0E131D",
        ).pack(padx=48, pady=(32, 6))

        tk.Label(
            panel,
            text="Enter your password to unlock",
            font=("Segoe UI", 11),
            fg="#94A3B8",
            bg="#0E131D",
        ).pack(pady=(0, 18))

        pwd_entry = tk.Entry(
            panel,
            show="*",
            font=("Segoe UI", 14),
            width=26,
            justify="center",
            bg="#161E2E",
            fg="#F8FAFC",
            insertbackground="#F8FAFC",
            relief="flat",
        )
        pwd_entry.pack(pady=(0, 12), ipady=6)
        pwd_entry.focus_set()

        error_lbl = tk.Label(
            panel,
            text="",
            font=("Segoe UI", 10),
            fg="#F87171",
            bg="#0E131D",
        )
        error_lbl.pack(pady=(0, 6))

        def check_pwd(event=None):
            if verify_password(pwd_entry.get()):
                self.unlock_screen()
            else:
                error_lbl.config(text="Incorrect password")
                pwd_entry.delete(0, tk.END)

        pwd_entry.bind("<Return>", check_pwd)

        tk.Button(
            panel,
            text="Unlock Screen",
            command=check_pwd,
            font=("Segoe UI", 11, "bold"),
            bg="#2563EB",
            fg="#FFFFFF",
            activebackground="#1D4ED8",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=28,
            pady=8,
            cursor="hand2",
        ).pack(pady=(6, 32))

    def unlock_screen(self):
        self.locked = False
        self.absence_elapsed = 0.0
        if self.lock_window is not None:
            try:
                self.lock_window.destroy()
            except tk.TclError:
                pass
            self.lock_window = None
        self._set_indicator(self.accent_green)
        self.status_var.set("UNLOCKED")
        self.substatus_var.set("Monitoring active")

    def _quit_app(self):
        self.running = False
        self.scan_active = False
        self.unlock_screen()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SmartPresenceLockApp(root)
    if app.running:
        root.mainloop()