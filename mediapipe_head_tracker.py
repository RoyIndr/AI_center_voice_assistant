# mediapipe_head_tracker.py

import cv2
import mediapipe as mp
import asyncio
import websockets
import json
import numpy as np

mp_face_mesh = mp.solutions.face_mesh
mp_drawing = mp.solutions.drawing_utils

async def send_head_pose():
    cap = cv2.VideoCapture(0)
    face_mesh = mp_face_mesh.FaceMesh(static_image_mode=False,
                                      max_num_faces=1,
                                      refine_landmarks=True,
                                      min_detection_confidence=0.5,
                                      min_tracking_confidence=0.5)

    async with websockets.connect("ws://localhost:8765") as ws:
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                continue

            h, w, _ = frame.shape
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb_frame)

            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0].landmark

                # Use selected landmarks for pose estimation
                nose = landmarks[1]  # Tip of the nose
                left_eye = landmarks[33]
                right_eye = landmarks[263]
                left_ear = landmarks[234]
                right_ear = landmarks[454]

                # Estimate dummy head pose angles based on landmark differences
                yaw = (right_eye.x - left_eye.x) * 100
                pitch = (nose.y - ((left_eye.y + right_eye.y)/2)) * 100
                roll = (left_ear.y - right_ear.y) * 100

                pose_data = {
                    "type": "head_pose",
                    "data": {
                        "yaw": yaw,
                        "pitch": pitch,
                        "roll": roll
                    }
                }
                await ws.send(json.dumps(pose_data))

            await asyncio.sleep(0.05)

    cap.release()

if __name__ == "__main__":
    asyncio.run(send_head_pose())
