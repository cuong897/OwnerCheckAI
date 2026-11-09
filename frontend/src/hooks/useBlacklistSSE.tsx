import { useEffect, useRef } from "react";
import { notification } from "antd";
import { getToken } from "@/hooks/useAuth";

interface BlacklistAlert {
  type: "blacklist_match";
  plate_text: string;
  camera_id: number;
  log_id: number;
  timestamp: string;
  owner_name?: string | null;
  vehicle_type?: string | null;
  note?: string | null;
  image_url?: string | null;
}

/**
 * Mount global SSE listener. Chỉ admin mới subscribe được /events/alerts.
 * Browser EventSource có auto-retry sẵn nên không cần manual reconnect.
 */
const ALERT_COOLDOWN_MS = 30_000;

export const useBlacklistSSE = (enabled: boolean = true) => {
  const lastAlertedRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    if (!enabled) return;

    const token = getToken();
    if (!token) return;

    const eventSource = new EventSource(
      `/events/alerts?token=${encodeURIComponent(token)}`
    );

    eventSource.addEventListener("blacklist_match", (event: MessageEvent) => {
      try {
        const data: BlacklistAlert = JSON.parse(event.data);

        const now = Date.now();
        const last = lastAlertedRef.current.get(data.plate_text);
        if (last !== undefined && now - last < ALERT_COOLDOWN_MS) return;
        lastAlertedRef.current.set(data.plate_text, now);

        // image_url payload là presigned URL trỏ MinIO — browser không reach.
        // Dùng endpoint backend proxy với log_id + token để render được trong <img>.
        const imgSrc = data.log_id
          ? `/recognition/logs/${data.log_id}/image?token=${encodeURIComponent(token)}`
          : null;

        notification.error({
          message: `🚨 CẢNH BÁO BLACKLIST: ${data.plate_text}`,
          description: (
            <div style={{ display: "flex", gap: 10 }}>
              {imgSrc && (
                <img
                  src={imgSrc}
                  alt={data.plate_text}
                  width={80}
                  height={56}
                  style={{
                    objectFit: "cover",
                    borderRadius: 4,
                    border: "1px solid rgba(255,78,80,0.5)",
                    flexShrink: 0,
                  }}
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                />
              )}
              <div style={{ minWidth: 0 }}>
                <div>
                  <strong>{data.owner_name || "Không xác định"}</strong>
                  {data.vehicle_type ? ` · ${data.vehicle_type}` : ""}
                </div>
                {data.note && (
                  <div style={{ fontStyle: "italic", marginTop: 4 }}>
                    "{data.note}"
                  </div>
                )}
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
                  Camera #{data.camera_id} · {new Date(data.timestamp).toLocaleTimeString("vi-VN")}
                </div>
              </div>
            </div>
          ),
          placement: "topRight",
          duration: 10,
          style: {
            background: "rgba(255, 78, 80, 0.12)",
            border: "1.5px solid #ff4e50",
            borderRadius: "8px",
            boxShadow: "0 0 25px rgba(255, 78, 80, 0.4)",
          },
        });

        // Browser desktop notification (nếu user đã grant permission)
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification(`🚨 BLACKLIST: ${data.plate_text}`, {
            body: `${data.owner_name || ""}${data.note ? " - " + data.note : ""}`,
            icon: imgSrc || undefined,
          });
        }
      } catch (err) {
        console.error("SSE parse error:", err);
      }
    });

    eventSource.onerror = (error) => {
      console.warn("SSE lost connection, browser will auto-retry...", error);
    };

    // Xin permission cho browser notification (silent fail nếu denied)
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }

    return () => {
      eventSource.close();
    };
  }, [enabled]);
};
