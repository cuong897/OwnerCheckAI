import { useState } from "react";
import { Table, Card, Button, Input, Select, Space, Tag, Modal, Form, Typography, App as AntdApp, Image } from "antd";
import { HistoryOutlined, EditOutlined, CheckCircleOutlined, SearchOutlined } from "@ant-design/icons";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth, getToken } from "@/hooks/useAuth";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

const { Text } = Typography;

interface Log {
  id: number;
  camera_id: number;
  plate_text: string;
  ocr_confidence: number | null;
  image_url: string | null;
  status: string;
  is_manual_verified: boolean;
  verified_plate_text: string | null;
  verified_by: number | null;
  timestamp: string;
}

export default function HistoryLogs() {
  const { isAdmin } = useAuth();
  const qc = useQueryClient();
  const { message } = AntdApp.useApp();

  const [filters, setFilters] = useState({ plate_text: "", camera_id: "", status: "" });
  const [editingLog, setEditingLog] = useState<Log | null>(null);
  const [form] = Form.useForm();

  const logsQuery = useQuery({
    queryKey: ["history-logs", filters],
    queryFn: async () => {
      const params = new URLSearchParams({ limit: "100" });
      if (filters.plate_text) params.append("plate_text", filters.plate_text);
      if (filters.camera_id) params.append("camera_id", filters.camera_id);
      if (filters.status) params.append("status", filters.status);
      return (await api.get<Log[]>(`/recognition/logs?${params}`)).data;
    },
  });

  const verifyMut = useMutation({
    mutationFn: async (values: { correctedPlate: string }) => {
      if (!editingLog) return;
      const me = JSON.parse(localStorage.getItem("currentUser") || "{}");
      await api.patch(`/recognition/logs/${editingLog.id}/verify`, {
        verified_plate_text: values.correctedPlate.toUpperCase().trim(),
        verified_by: me.id || 1,
      });
    },
    onSuccess: () => {
      message.success("Đã xác minh biển số");
      qc.invalidateQueries({ queryKey: ["history-logs"] });
      setEditingLog(null);
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Lỗi xác minh"),
  });

  const handleOpenVerify = (log: Log) => {
    setEditingLog(log);
    form.setFieldsValue({ correctedPlate: log.verified_plate_text || log.plate_text });
  };

  const columns: ColumnsType<Log> = [
    {
      title: "Ảnh",
      dataIndex: "image_url",
      width: 80,
      render: (url, log) =>
        url ? (
          <Image
            src={`/recognition/logs/${log.id}/image?token=${encodeURIComponent(getToken() || "")}`}
            width={60}
            height={40}
            style={{ objectFit: "cover", borderRadius: 4 }}
          />
        ) : (
          <div style={{ width: 60, height: 40, background: "#222", borderRadius: 4 }} />
        ),
    },
    {
      title: "Thời gian",
      dataIndex: "timestamp",
      width: 160,
      render: (t) => <Text style={{ color: "#8c8c8c" }}>{dayjs(t).format("HH:mm:ss DD/MM/YYYY")}</Text>,
    },
    { title: "Camera", dataIndex: "camera_id", width: 90, render: (id) => `#${id}` },
    {
      title: "Biển AI",
      dataIndex: "plate_text",
      render: (text) => <span style={{ fontFamily: "monospace", color: "#ff7875" }}>{text || "(rỗng)"}</span>,
    },
    {
      title: "Confidence",
      dataIndex: "ocr_confidence",
      width: 110,
      render: (c) =>
        c !== null ? <Tag color={c >= 0.7 ? "green" : "orange"}>{(c * 100).toFixed(0)}%</Tag> : "-",
    },
    {
      title: "Trạng thái",
      dataIndex: "status",
      width: 110,
      render: (s, log) =>
        log.is_manual_verified ? (
          <Tag color="success" icon={<CheckCircleOutlined />}>Verified</Tag>
        ) : (
          <Tag color={s === "SUCCESS" ? "green" : s === "FAILED" ? "red" : "default"}>{s}</Tag>
        ),
    },
    {
      title: "Hành động",
      width: 110,
      render: (_, log) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          disabled={log.is_manual_verified && !isAdmin}
          onClick={() => handleOpenVerify(log)}
        >
          Verify
        </Button>
      ),
    },
  ];

  return (
    <>
      <Card className="glass-card" style={{ marginBottom: 24 }}>
        <Space size="middle" wrap>
          <HistoryOutlined style={{ color: "#00f2fe", fontSize: 18 }} />
          <Text style={{ fontSize: 16, fontWeight: 600, color: "#fff" }}>Lịch sử nhận diện</Text>
          <Input
            prefix={<SearchOutlined />}
            placeholder="Tìm theo biển số"
            allowClear
            onChange={(e) => setFilters((f) => ({ ...f, plate_text: e.target.value }))}
            style={{ width: 220 }}
          />
          <Input
            placeholder="Camera ID"
            allowClear
            onChange={(e) => setFilters((f) => ({ ...f, camera_id: e.target.value }))}
            style={{ width: 140 }}
          />
          <Select
            placeholder="Trạng thái"
            allowClear
            onChange={(v) => setFilters((f) => ({ ...f, status: v || "" }))}
            style={{ width: 160 }}
            options={[
              { value: "SUCCESS", label: "SUCCESS" },
              { value: "FAILED", label: "FAILED" },
              { value: "PENDING", label: "PENDING" },
            ]}
          />
        </Space>
      </Card>

      <Card className="glass-card" styles={{ body: { padding: 0 } }}>
        <Table
          rowKey="id"
          loading={logsQuery.isLoading}
          dataSource={logsQuery.data}
          columns={columns}
          pagination={{ pageSize: 15 }}
        />
      </Card>

      <Modal
        open={!!editingLog}
        title={`Xác minh log #${editingLog?.id}`}
        onCancel={() => setEditingLog(null)}
        onOk={() => form.submit()}
        confirmLoading={verifyMut.isPending}
        okText="Lưu"
        cancelText="Hủy"
      >
        {editingLog && (
          <Form form={form} layout="vertical" onFinish={(v) => verifyMut.mutate(v)}>
            <p>
              <Text type="secondary">Biển AI đọc:</Text>{" "}
              <Text strong style={{ color: "#ff7875" }}>{editingLog.plate_text}</Text>
            </p>
            <Form.Item
              name="correctedPlate"
              label="Biển số chính xác"
              rules={[{ required: true, message: "Vui lòng nhập biển số" }]}
            >
              <Input
                placeholder="30A-12345"
                style={{ fontFamily: "monospace", textTransform: "uppercase", textAlign: "center", fontSize: 16 }}
              />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </>
  );
}
