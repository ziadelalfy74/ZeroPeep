# ZeroPeep — Smart Presence Lock & Privacy Guard

**ZeroPeep** is an intelligent desktop privacy application that automatically monitors user presence via webcam and locks your screen with a full-screen blackout overlay the moment you step away or an unauthorized person sits in front of your laptop.

---

## Key Features

- **Real-Time Presence Detection:** Uses computer vision (`OpenCV` & `MediaPipe Face Landmarker`) to verify the owner's presence continuously.
- **6-Step Verified Action Scan:** Guided enrollment process (center, left, right, up, down, smile) to accurately register the owner's face across angles.
- **Smart Adaptive Lighting Filter:** Automatically adjusts image processing to handle low-light or varying lighting conditions.
- **Instant Blackout Overlay:** Locks the screen with an always-on-top full-screen overlay after a configurable absence duration.
- **Auto-Unlock on Return:** Optionally unlocks the screen automatically once the owner returns, or via password authentication.
- **Password & Emergency Override:** Secure local password verification (`password.hash`) with a configurable emergency exit shortcut.

---

## Project Structure

```text
ZeroPeep/
├── main.py                  # Main GUI application & lock screen controller
├── face_guard.py            # Face detection, landmark analysis & smart filter logic
├── config.py                # Application settings, thresholds & password utilities
├── face_landmarker.task     # Pre-trained MediaPipe Face Landmarker model
├── zeropeep.ico             # Application icon
├── start.bat                # Quick Windows launcher script
└── README.md                # Project documentation
```

---

## Prerequisites & Installation

1. **Python 3.10+** installed on Windows.
2. Clone the repository:
   ```bash
   git clone https://github.com/ziadelalfy74/ZeroPeep.git
   cd ZeroPeep
   ```
3. Install required dependencies:
   ```bash
   pip install opencv-python pillow mediapipe numpy
   ```

---

## Usage

1. Run the application:
   ```bash
   python main.py
   ```
2. **First-Time Setup:**
   - Set an unlock password when prompted.
   - Complete the **6-Step Guided Scan** so ZeroPeep can recognize your face.
3. **Configuration:**
   - Adjust absence timeout, camera index, and emergency exit shortcut inside `config.py`.

