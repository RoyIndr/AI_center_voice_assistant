// UnityAvatarController.cs
using UnityEngine;
using NativeWebSocket;
using System.Collections;
using System.IO;
using System;
using UnityEngine.Networking;

[RequireComponent(typeof(AudioSource))]
public class UnityAvatarController : MonoBehaviour
{
    private WebSocket websocket;
    public string serverUrl = "ws://localhost:8765";
    public AudioSource audioSource;
    public SkinnedMeshRenderer avatarMouth; // For simple viseme-based lip sync
    public Transform headBone; // Bone to rotate

    void Start()
    {
        audioSource = GetComponent<AudioSource>();
        websocket = new WebSocket(serverUrl);

        websocket.OnMessage += OnMessageReceived;
        websocket.Connect();
    }

    async void OnMessageReceived(byte[] bytes)
    {
        string message = System.Text.Encoding.UTF8.GetString(bytes);
        Debug.Log("Received: " + message);

        var json = JsonUtility.FromJson<WSMessage>(message);

        if (json.type == "reply")
        {
            string audioPath = Path.Combine(Application.streamingAssetsPath, "reply.wav");
            StartCoroutine(PlayReply(audioPath));
        }
        else if (json.type == "head_pose")
        {
            headBone.localRotation = Quaternion.Euler(json.data.pitch, json.data.yaw, json.data.roll);
        }
    }

    IEnumerator PlayReply(string path)
    {
        using UnityWebRequest www = UnityWebRequestMultimedia.GetAudioClip("file://" + path, AudioType.WAV);
        yield return www.SendWebRequest();

        if (www.result == UnityWebRequest.Result.Success)
        {
            AudioClip clip = DownloadHandlerAudioClip.GetContent(www);
            audioSource.clip = clip;
            audioSource.Play();
            StartCoroutine(SimpleLipSync(clip));
        }
        else
        {
            Debug.LogError("Failed to load audio clip: " + www.error);
        }
    }

    IEnumerator SimpleLipSync(AudioClip clip)
    {
        float duration = clip.length;
        float time = 0f;

        while (time < duration)
        {
            float mouthVal = Mathf.PingPong(Time.time * 10f, 100f); // Simulate mouth motion
            avatarMouth.SetBlendShapeWeight(0, mouthVal);
            time += Time.deltaTime;
            yield return null;
        }

        avatarMouth.SetBlendShapeWeight(0, 0);
    }

    void Update()
    {
        websocket.DispatchMessageQueue();
    }

    private void OnApplicationQuit()
    {
        websocket.Close();
    }

    [Serializable]
    public class WSMessage
    {
        public string type;
        public string text;
        public PoseData data;
    }

    [Serializable]
    public class PoseData
    {
        public float yaw;
        public float pitch;
        public float roll;
    }
}