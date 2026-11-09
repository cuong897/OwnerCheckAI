import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, Input, Radio, Row, Col, Table, Space, Tag, Typography, Alert, Spin } from "antd";
import { SearchOutlined, UserOutlined, ClockCircleOutlined, AlertOutlined } from "@ant-design/icons";
import { usePrivacy } from "@/context/PrivacyContext";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/api/client";
import dayjs from "dayjs";
import type { ColumnsType } from "antd/es/table";

const { Title, Text } = Typography;

interface Vehicle {
  plate_number: string;
  owner_name: string | null;
  vehicle_type: string | null;
  brand: string | null;
  color: string | null;
  created_at: string;
}

interface Watch {
  id: number;
  plate_number: string;
  category: "BLACKLIST" | "WHITELIST";
  note: string | null;
}

interface Log {
  id: number;
  camera_id: number;
  plate_text: string;
  ocr_confidence: number | null;
  timestamp: string;
}

export default function Lookup() {
  const { blurOwnerInfo } = usePrivacy();
  const { isAdmin } = useAuth();
  const isBlurActive = isAdmin ? blurOwnerInfo : true;

  const [searchType, setSearchType] = useState<"plate" | "name">("plate");
  const [inputValue, setInputValue] = useState("");
  const [searchTrigger, setSearchTrigger] = useState("");

  const handleSearch = () => setSearchTrigger(inputValue.trim().toUpperCase());

  // Search by plate (single vehicle)
  const vehicleQuery = useQuery({
    queryKey: ["lookup-plate", searchTrigger, searchType],
    queryFn: async () => {
      if (!searchTrigger || searchType !== "plate") return null;
      try {
        return (await api.get<Vehicle>(`/vehicles/${encodeURIComponent(searchTrigger)}`)).data;
      } catch {
        return null;
      }
    },
    enabled: !!searchTrigger && searchType === "plate",
  });

  // Search by owner name (list)
  const ownersQuery = useQuery({
    queryKey: ["lookup-owner", searchTrigger, searchType],
    queryFn: async () => {
      if (!searchTrigger || searchType !== "name") return [];
      return (await api.get<Vehicle[]>(`/vehicles?owner_name=${encodeURIComponent(searchTrigger)}`)).data;
    },
    enabled: !!searchTrigger && searchType === "name",
  });

  const plateForChecks = vehicleQuery.data?.plate_number;

  const watchlistQuery = useQuery({
    queryKey: ["lookup-watch", plateForChecks],
    queryFn: async () => {
      if (!plateForChecks) return null;
      const { data } = await api.get<Watch[]>(`/watchlists?plate_number=${encodeURIComponent(plateForChecks)}`);
      return data[0] || null;
    },
    enabled: !!plateForChecks,
  });

  const historyQuery = useQuery({
    queryKey: ["lookup-history", plateForChecks],
    queryFn: async () => {
      if (!plateForChecks) return [];
      return (await api.get<Log[]>(`/recognition/logs?plate_text=${encodeURIComponent(plateForChecks)}&limit=50`)).data;
    },
    enabled: !!plateForChecks,
  });

  const isLoading =
    vehicleQuery.isFetching || ownersQuery.isFetching || watchlistQuery.isFetching || historyQuery.isFetching;

  const maskName = (name: string | null) => {
    if (!name) return "-";
    if (!isBlurActive) return name;
    const parts = name.trim().split(" ");
    if (parts.length <= 1) return name;
    return `${parts[0]} ${"*".repeat(parts.length - 2)} ${parts[parts.length - 1]}`;
  };

  const logsColumns: ColumnsType<Log> = [
    { title: "Thời gian", dataIndex: "timestamp", render: (t) => dayjs(t).format("HH:mm:ss DD/MM/YYYY") },
    { title: "Camera", dataIndex: "camera_id", render: (id) => `Camera #${id}`, width: 130 },
    {
      title: "Confidence",
      dataIndex: "ocr_confidence",
      width: 120,
      render: (c) => (c !== null ? <Tag color={c >= 0.7 ? "green" : "orange"}>{(c * 100).toFixed(0)}%</Tag> : "-"),
    },
  ];

  const ownerColumns: ColumnsType<Vehicle> = [
    { title: "Biển số", dataIndex: "plate_number" },
    { title: "Chủ", dataIndex: "owner_name", render: (n) => <span className={isBlurActive ? "pii-blur" : ""}>{maskName(n)}</span> },
    { title: "Hãng", dataIndex: "brand" },
    { title: "Loại", dataIndex: "vehicle_type" },
    { title: "Màu", dataIndex: "color" },
  ];

  return (
    <div>
      <Card className="glass-card" style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0, color: "#fff", marginBottom: 16 }} className="gradient-text-cyan-blue">
          <SearchOutlined /> Tra Cứu Toàn Diện Phương Tiện
        </Title>

        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Radio.Group
            value={searchType}
            onChange={(e) => {
              setSearchType(e.target.value);
              setInputValue("");
              setSearchTrigger("");
            }}
          >
            <Radio value="plate">Theo biển số</Radio>
            <Radio value="name">Theo tên chủ xe</Radio>
          </Radio.Group>

          <Input.Search
            placeholder={searchType === "plate" ? "VD: 30A-12345" : "VD: Nguyễn"}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onSearch={handleSearch}
            enterButton="Tìm kiếm"
            loading={isLoading}
            size="large"
            style={{ maxWidth: 600 }}
          />
        </Space>
      </Card>

      {searchTrigger && searchType === "name" && (
        <Card title="Kết quả theo tên chủ xe" className="glass-card">
          <Table
            rowKey="plate_number"
            loading={ownersQuery.isLoading}
            dataSource={ownersQuery.data}
            columns={ownerColumns}
            locale={{ emptyText: `Không tìm thấy chủ xe nào khớp "${searchTrigger}"` }}
          />
        </Card>
      )}

      {searchTrigger && searchType === "plate" && !vehicleQuery.data && !vehicleQuery.isLoading && (
        <Card className="glass-card">
          <Text type="warning">Không tìm thấy xe với biển số "{searchTrigger}"</Text>
        </Card>
      )}

      {vehicleQuery.data && (
        <div style={{ position: "relative" }}>
          {isLoading && (
            <div style={{ position: "absolute", top: 40, left: "50%", transform: "translateX(-50%)", zIndex: 10 }}>
              <Spin size="large" />
            </div>
          )}

          <Row gutter={[24, 24]}>
            <Col xs={24} md={10}>
              <Space direction="vertical" style={{ width: "100%" }} size="large">
                <Card
                  title={
                    <Space>
                      <UserOutlined style={{ color: "#00f2fe" }} />
                      <span style={{ color: "#fff" }}>Thông tin chủ sở hữu</span>
                    </Space>
                  }
                  className="glass-card"
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div>
                      <Text type="secondary" style={{ fontSize: 11, display: "block" }}>BIỂN SỐ</Text>
                      <span
                        style={{
                          background: "#f0f2f5",
                          color: "#000",
                          padding: "2px 10px",
                          borderRadius: 4,
                          fontWeight: 800,
                          fontSize: 20,
                          border: "1.5px solid #000",
                          fontFamily: "monospace",
                          display: "inline-block",
                        }}
                      >
                        {vehicleQuery.data.plate_number}
                      </span>
                    </div>

                    <div>
                      <Text type="secondary" style={{ fontSize: 11, display: "block" }}>HỌ VÀ TÊN</Text>
                      <Text strong style={{ fontSize: 15, color: "#fff" }} className={isBlurActive ? "pii-blur" : ""}>
                        {maskName(vehicleQuery.data.owner_name)}
                      </Text>
                    </div>

                    <div>
                      <Text type="secondary" style={{ fontSize: 11, display: "block" }}>LOẠI XE</Text>
                      <Text style={{ color: "#fff" }}>{vehicleQuery.data.vehicle_type || "-"}</Text>
                    </div>

                    <div>
                      <Text type="secondary" style={{ fontSize: 11, display: "block" }}>HÃNG / MÀU</Text>
                      <Text style={{ color: "#fff" }}>
                        {[vehicleQuery.data.brand, vehicleQuery.data.color].filter(Boolean).join(" · ") || "-"}
                      </Text>
                    </div>

                    <div>
                      <Text type="secondary" style={{ fontSize: 11, display: "block" }}>ĐĂNG KÝ</Text>
                      <Text style={{ color: "#fff" }}>{dayjs(vehicleQuery.data.created_at).format("DD/MM/YYYY")}</Text>
                    </div>
                  </div>
                </Card>

                {watchlistQuery.data?.category === "BLACKLIST" && (
                  <Card className="blacklist-card-alert" style={{ borderRadius: 12 }}>
                    <Space align="start">
                      <AlertOutlined style={{ fontSize: 24, color: "#ff4d4f", marginTop: 2 }} />
                      <div>
                        <Title level={5} style={{ color: "#ff4d4f", margin: 0, fontWeight: 700 }}>
                          Cảnh báo: BLACKLIST
                        </Title>
                        <Text style={{ color: "#ff7875", fontSize: 13, display: "block", marginTop: 4 }}>
                          {watchlistQuery.data.note}
                        </Text>
                      </div>
                    </Space>
                  </Card>
                )}

                {watchlistQuery.data?.category === "WHITELIST" && (
                  <Alert
                    message="Phương tiện WHITELIST"
                    description={watchlistQuery.data.note}
                    type="info"
                    showIcon
                    style={{
                      background: "rgba(79, 172, 254, 0.1)",
                      border: "1px solid rgba(79, 172, 254, 0.3)",
                    }}
                  />
                )}
              </Space>
            </Col>

            <Col xs={24} md={14}>
              <Card
                title={
                  <Space>
                    <ClockCircleOutlined style={{ color: "#00f2fe" }} />
                    <span style={{ color: "#fff" }}>Lịch sử nhận diện</span>
                  </Space>
                }
                className="glass-card"
              >
                <Table
                  dataSource={historyQuery.data}
                  columns={logsColumns}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  locale={{ emptyText: "Chưa có lịch sử nhận diện cho xe này" }}
                />
              </Card>
            </Col>
          </Row>
        </div>
      )}
    </div>
  );
}
