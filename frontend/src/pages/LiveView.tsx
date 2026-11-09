import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Row, Col, Card, Select, Badge, Typography, Tag, Space, Empty, Spin, message } from "antd";
import { VideoCameraOutlined, AlertOutlined, SafetyOutlined, DisconnectOutlined } from "@ant-design/icons";
import { usePrivacy } from "@/context/PrivacyContext";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/api/client";
import { getToken } from "@/hooks/useAuth";
import { useRecognitionSSE, type PlateTrack } from "@/hooks/useRecognitionSSE";
import dayjs from "dayjs";

const { Text } = Typography;

interface Camera {
  id: number;
  camera_name: string;
  location: string | null;
  status: string;
}

const MIN_CONFIDENCE = 0.5;

export default function LiveView() {
  const { blurOwnerInfo } = usePrivacy();
  const { isAdmin } = useAuth();
  const isBlurActive = isAdmin ? blurOwnerInfo : true;

  const [cameraId, setCameraId] = useState<number | null>(null);
  const token = getToken();

  const camerasQuery = useQuery({
    queryKey: ["cameras"],
    queryFn: async () => (await api.get<Camera[]>("/cameras")).data,
    refetchInterval: 5_000, // bắt thay đổi status (ACTIVE / INACTIVE) từ tab khác
  });

  // Memo theo data ref → tránh tạo array mới mỗi render khiến useEffect chạy thừa
  const activeCameras = useMemo(
    () => (camerasQuery.data || []).filter((c) => c.status === "ACTIVE"),
    [camerasQuery.data],
  );

  // Auto-fallback: nếu camera đang chọn không còn ACTIVE (vd: admin chuyển INACTIVE),
  // tự deselect / chuyển sang camera ACTIVE khác để tránh hiện màn hình đen.
  useEffect(() => {
    if (cameraId === null) return;
    if (!camerasQuery.data) return;
    const stillActive = activeCameras.some((c) => c.id === cameraId);
    if (stillActive) return;
    const next = activeCameras[0]?.id ?? null;
    setCameraId(next);
    const currentCam = camerasQuery.data.find((c) => c.id === cameraId);
    const newCam = next ? activeCameras[0] : null;
    message.warning(
      newCam
        ? `${currentCam?.camera_name ?? `Camera #${cameraId}`} không còn ACTIVE — đã chuyển sang ${newCam.camera_name}.`
        : `${currentCam?.camera_name ?? `Camera #${cameraId}`} không còn ACTIVE — không có camera nào khác đang ACTIVE.`
    );
  }, [camerasQuery.data, cameraId, activeCameras]);

  const { tracks, connected } = useRecognitionSSE(cameraId);

  const streamUrl = cameraId && token ? `/streams/cameras/${cameraId}?token=${encodeURIComponent(token)}` : null;

  // Stream state: connecting → live (onLoad) | error (onError / timeout 10s)
  const [streamState, setStreamState] = useState<"connecting" | "live" | "error">("connecting");
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    if (!streamUrl) return;
    setStreamState("connecting");
    // Timeout 10s — nếu ingestor không publish frame nào (RTSP fail, mediamtx
    // path không tồn tại...) thì hiện thông báo thay vì để màn hình đen mãi.
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    timeoutRef.current = window.setTimeout(() => {
      setStreamState((s) => (s === "connecting" ? "error" : s));
    }, 10_000);
    return () => {
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    };
  }, [streamUrl]);

  // Track active hiển thị chính = track mới nhất (đầu list)
  const activeTrack: PlateTrack | null = tracks[0] || null;
  const isBlacklisted = activeTrack?.alert === true;
  const isLowConfidence = activeTrack !== null && activeTrack.best_conf < MIN_CONFIDENCE;

  const maskName = (name: string | null | undefined) => {
    if (!name) return "-";
    if (!isBlurActive) return name;
    const parts = name.trim().split(" ");
    if (parts.length <= 1) return name;
    return `${parts[0]} ${"*".repeat(parts.length - 2)} ${parts[parts.length - 1]}`;
  };

  return (
    <Row gutter={[24, 24]}>
      <Col xs={24} lg={16}>
        <Card
          title={
            <Space>
              <VideoCameraOutlined style={{ color: "#00f2fe" }} />
              <span style={{ color: "#fff", fontWeight: 600 }}>Luồng Video Trực Tuyến</span>
            </Space>
          }
          extra={
            <Select
              placeholder="Chọn camera..."
              value={cameraId}
              onChange={setCameraId}
              options={activeCameras.map((c) => ({
                value: c.id,
                label: `${c.camera_name}${c.location ? " — " + c.location : ""}`,
              }))}
              loading={camerasQuery.isLoading}
              style={{ width: 280 }}
            />
          }
          className="glass-card"
        >
          <div
            style={{
              position: "relative",
              width: "100%",
              aspectRatio: "16/9",
              background: "#000",
              borderRadius: "8px",
              overflow: "hidden",
              border: "1px solid rgba(255,255,255,0.08)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            {streamUrl ? (
              <>
                <img
                  // key=cameraId: remount img khi đổi camera để clear frame cũ ngay
                  key={cameraId}
                  src={streamUrl}
                  alt="Live stream"
                  onLoad={() => setStreamState("live")}
                  onError={() => setStreamState("error")}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "contain",
                    // Browser dùng nearest-neighbor cho text/edges thay vì bilinear blur
                    // khi container hiển thị > kích thước native frame.
                    imageRendering: "-webkit-optimize-contrast",
                    // Ẩn img khi chưa có frame (tránh broken-image icon)
                    visibility: streamState === "live" ? "visible" : "hidden",
                  }}
                />
                {streamState === "connecting" && (
                  <div style={{
                    position: "absolute", inset: 0, display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center", gap: 12, color: "#aaa",
                  }}>
                    <Spin size="large" />
                    <Text style={{ color: "#aaa" }}>Đang kết nối camera...</Text>
                  </div>
                )}
                {streamState === "error" && (
                  <div style={{
                    position: "absolute", inset: 0, display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center", gap: 8, color: "#ff7875",
                  }}>
                    <DisconnectOutlined style={{ fontSize: 36 }} />
                    <Text style={{ color: "#ff7875", fontWeight: 600 }}>Không kết nối được camera</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      Kiểm tra RTSP URL hoặc trạng thái ingestor
                    </Text>
                  </div>
                )}
                <div style={{ position: "absolute", top: 12, left: 12, display: "flex", gap: 8 }}>
                  <Tag color={streamState === "live" ? "red" : "default"} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <Badge status={streamState === "live" ? "processing" : "default"} /> LIVE
                  </Tag>
                  <Tag color={connected ? "green" : "default"} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <Badge status={connected ? "success" : "default"} />
                    AI {connected ? "ONLINE" : "OFFLINE"}
                  </Tag>
                </div>
              </>
            ) : (
              <Empty
                description={
                  activeCameras.length === 0
                    ? "Chưa có camera ACTIVE — vào /admin/cameras để thêm"
                    : "Chọn camera để xem live"
                }
              />
            )}
          </div>
        </Card>
      </Col>

      <Col xs={24} lg={8}>
        <Card
          title={
            <Space>
              <SafetyOutlined style={{ color: "#00f2fe" }} />
              <span style={{ color: "#fff", fontWeight: 600 }}>Kết Quả Nhận Diện AI</span>
            </Space>
          }
          className="glass-card"
        >
          {!cameraId && <Empty description="Chưa chọn camera" />}
          {cameraId && !activeTrack && <Empty description="Đang chờ AI nhận diện..." />}
          {activeTrack && (
            <Card
              className={isBlacklisted ? "blacklist-card-alert" : ""}
              style={{ transition: "all 0.3s ease", borderRadius: 8 }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                {isBlacklisted && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#ff4d4f", fontWeight: 700 }}>
                    <AlertOutlined />
                    <Text style={{ color: "#ff4d4f", fontWeight: 700 }}>PHƯƠNG TIỆN BỊ CẢNH BÁO</Text>
                  </div>
                )}

                <div>
                  <Text type="secondary" style={{ fontSize: 11, display: "block" }}>BIỂN SỐ</Text>
                  <Space align="center" wrap>
                    <span
                      style={{
                        background: "#f0f2f5",
                        color: "#000",
                        padding: "4px 14px",
                        borderRadius: 6,
                        fontWeight: 800,
                        fontSize: 24,
                        border: "2px solid #000",
                        fontFamily: "monospace",
                        display: "inline-block",
                        marginTop: 4,
                      }}
                    >
                      {activeTrack.plate_text || "—"}
                    </span>
                    {isLowConfidence && <Tag color="warning">conf thấp</Tag>}
                  </Space>
                </div>

                <div>
                  <Text type="secondary" style={{ fontSize: 11, display: "block" }}>CHỦ SỞ HỮU</Text>
                  {activeTrack.owner.registered ? (
                    <Text strong style={{ fontSize: 15, color: "#fff" }} className={isBlurActive ? "pii-blur" : ""}>
                      {maskName(activeTrack.owner.owner_name)}
                    </Text>
                  ) : (
                    <Text type="warning">⚠ Xe chưa đăng ký</Text>
                  )}
                </div>

                {activeTrack.owner.registered && (
                  <div>
                    <Text type="secondary" style={{ fontSize: 11, display: "block" }}>PHƯƠNG TIỆN</Text>
                    <Text style={{ color: "#fff" }}>
                      {[activeTrack.owner.brand, activeTrack.owner.color, activeTrack.owner.vehicle_type]
                        .filter(Boolean).join(" · ") || "-"}
                    </Text>
                  </div>
                )}

                {activeTrack.watchlist?.note && (
                  <Text italic style={{ color: isBlacklisted ? "#ff7875" : "#52c41a", fontSize: 12 }}>
                    "{activeTrack.watchlist.note}"
                  </Text>
                )}

                {activeTrack.image_url && activeTrack.log_id && token && (
                  <div>
                    <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>
                      ẢNH BIỂN
                    </Text>
                    <img
                      src={`/recognition/logs/${activeTrack.log_id}/image?token=${encodeURIComponent(token)}`}
                      alt={activeTrack.plate_text}
                      style={{
                        width: "100%",
                        maxHeight: 120,
                        objectFit: "contain",
                        borderRadius: 6,
                        border: isBlacklisted
                          ? "1.5px solid #ff4d4f"
                          : "1px solid rgba(255,255,255,0.12)",
                        background: "#000",
                        imageRendering: "-webkit-optimize-contrast",
                      }}
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                    />
                  </div>
                )}

                <Row gutter={16} style={{ borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 12 }}>
                  <Col span={12}>
                    <Text type="secondary" style={{ fontSize: 10, display: "block" }}>CONFIDENCE</Text>
                    <Text strong style={{
                      color: activeTrack.best_conf >= 0.7 ? "#52c41a" : activeTrack.best_conf >= MIN_CONFIDENCE ? "#faad14" : "#ff7875",
                    }}>
                      {(activeTrack.best_conf * 100).toFixed(0)}%
                    </Text>
                  </Col>
                  <Col span={12}>
                    <Text type="secondary" style={{ fontSize: 10, display: "block" }}>THỜI GIAN</Text>
                    <Text style={{ color: "#fff", fontSize: 12 }}>
                      {dayjs(activeTrack.last_seen).format("HH:mm:ss")}
                    </Text>
                  </Col>
                </Row>
              </div>
            </Card>
          )}
        </Card>

      </Col>
    </Row>
  );
}
