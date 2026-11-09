import { useState } from "react";
import { Table, Card, Button, Modal, Form, Input, Space, Popconfirm, Tag, App as AntdApp, Upload, Typography } from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined, ImportOutlined, CarOutlined } from "@ant-design/icons";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { usePrivacy } from "@/context/PrivacyContext";
import { useAuth } from "@/hooks/useAuth";
import type { ColumnsType } from "antd/es/table";

interface Vehicle {
  plate_number: string;
  owner_name: string | null;
  vehicle_type: string | null;
  brand: string | null;
  color: string | null;
}

export default function VehiclesManage() {
  const qc = useQueryClient();
  const { message, modal } = AntdApp.useApp();
  const { blurOwnerInfo } = usePrivacy();
  const { isAdmin } = useAuth();
  const isBlurActive = isAdmin ? blurOwnerInfo : true;

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Vehicle | null>(null);
  const [form] = Form.useForm();

  const query = useQuery({
    queryKey: ["vehicles-admin"],
    queryFn: async () => (await api.get<Vehicle[]>("/vehicles?limit=500")).data,
  });

  const upsertMut = useMutation({
    mutationFn: async (data: any) => {
      const payload = { ...data, plate_number: data.plate_number?.toUpperCase() };
      return editing
        ? (await api.patch(`/vehicles/${encodeURIComponent(editing.plate_number)}`, payload)).data
        : (await api.post("/vehicles", payload)).data;
    },
    onSuccess: () => {
      message.success(editing ? "Cập nhật thành công" : "Thêm xe thành công");
      qc.invalidateQueries({ queryKey: ["vehicles-admin"] });
      setOpen(false);
      setEditing(null);
      form.resetFields();
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Lỗi"),
  });

  const deleteMut = useMutation({
    mutationFn: async (plate: string) => api.delete(`/vehicles/${encodeURIComponent(plate)}`),
    onSuccess: () => {
      message.success("Đã xoá");
      qc.invalidateQueries({ queryKey: ["vehicles-admin"] });
    },
    onError: (err: any) => {
      message.error(err.response?.data?.detail || "Không xoá được vehicle");
    },
  });

  const handleBulkImport = async (file: File) => {
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      if (!Array.isArray(data)) throw new Error("File phải là JSON array");
      const { data: result } = await api.post("/vehicles/bulk-import", data);
      modal.success({
        title: "Import xong",
        width: 480,
        content: (
          <div>
            <p>Tổng: <strong>{result.total}</strong></p>
            <p>Imported: <strong style={{ color: "#52c41a" }}>{result.imported}</strong></p>
            <p>Skipped: <strong style={{ color: "#faad14" }}>{result.skipped.length}</strong></p>
            {result.skipped.length > 0 && (
              <details>
                <summary>Chi tiết skip</summary>
                <ul style={{ maxHeight: 200, overflow: "auto" }}>
                  {result.skipped.map((s: any, i: number) => (
                    <li key={i}>{s.plate_number}: {s.reason}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ),
      });
      qc.invalidateQueries({ queryKey: ["vehicles-admin"] });
    } catch (err: any) {
      message.error(err.message || err.response?.data?.detail || "Lỗi import");
    }
    return false;
  };

  const maskName = (name: string | null) => {
    if (!name) return "-";
    if (!isBlurActive) return name;
    const parts = name.trim().split(" ");
    if (parts.length <= 1) return name;
    return `${parts[0]} ${"*".repeat(parts.length - 2)} ${parts[parts.length - 1]}`;
  };

  const openCreate = () => { setEditing(null); form.resetFields(); setOpen(true); };
  const openEdit = (v: Vehicle) => { setEditing(v); form.setFieldsValue(v); setOpen(true); };

  const columns: ColumnsType<Vehicle> = [
    {
      title: "Biển số",
      dataIndex: "plate_number",
      width: 130,
      render: (p) => (
        <span style={{
          fontFamily: "monospace",
          fontWeight: 700,
          background: "#f0f2f5",
          color: "#000",
          padding: "2px 8px",
          borderRadius: 4,
          border: "1.5px solid #000",
        }}>{p}</span>
      ),
    },
    {
      title: "Chủ xe",
      dataIndex: "owner_name",
      render: (n) => <span className={isBlurActive ? "pii-blur" : ""}>{maskName(n)}</span>,
    },
    { title: "Loại", dataIndex: "vehicle_type", width: 130, render: (t) => t ? <Tag color="geekblue">{t}</Tag> : "-" },
    { title: "Hãng", dataIndex: "brand", width: 150 },
    { title: "Màu", dataIndex: "color", width: 110 },
    {
      title: "Hành động",
      width: 180,
      render: (_, v) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(v)}>Sửa</Button>
          <Popconfirm title={`Xoá xe ${v.plate_number}?`} onConfirm={() => deleteMut.mutate(v.plate_number)}>
            <Button size="small" danger icon={<DeleteOutlined />}>Xoá</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card
        className="glass-card"
        style={{ marginBottom: 24 }}
        styles={{ body: { display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 } }}
      >
        <Space>
          <CarOutlined style={{ color: "#00f2fe", fontSize: 18 }} />
          <span style={{ fontSize: 16, fontWeight: 600, color: "#fff" }}>Quản lý xe & chủ xe</span>
        </Space>
        <Space>
          <Upload accept=".json" beforeUpload={handleBulkImport} showUploadList={false}>
            <Button icon={<ImportOutlined />}>Bulk import JSON</Button>
          </Upload>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>Thêm xe</Button>
        </Space>
      </Card>

      <Card className="glass-card" styles={{ body: { padding: 0 } }}>
        <Typography.Text type="secondary" style={{ display: "block", padding: "12px 16px 0", fontSize: 12 }}>
          Format JSON: <code>[{"{"} "plate_number": "30A-12345", "owner_name": "...", "brand": "..." {"}"}]</code>
        </Typography.Text>
        <Table rowKey="plate_number" loading={query.isLoading} dataSource={query.data} columns={columns} pagination={{ pageSize: 10 }} />
      </Card>

      <Modal
        open={open}
        title={editing ? `Sửa ${editing.plate_number}` : "Đăng ký xe mới"}
        onCancel={() => { setOpen(false); setEditing(null); form.resetFields(); }}
        onOk={() => form.submit()}
        confirmLoading={upsertMut.isPending}
        okText="Lưu"
        cancelText="Hủy"
      >
        <Form form={form} layout="vertical" onFinish={(v) => upsertMut.mutate(v)}>
          {!editing && (
            <Form.Item name="plate_number" label="Biển số" rules={[{ required: true }]}>
              <Input placeholder="30A-12345" style={{ textTransform: "uppercase" }} />
            </Form.Item>
          )}
          <Form.Item name="owner_name" label="Chủ xe"><Input /></Form.Item>
          <Form.Item name="vehicle_type" label="Loại xe"><Input placeholder="Ô tô con, SUV, Xe tải..." /></Form.Item>
          <Form.Item name="brand" label="Hãng"><Input placeholder="Toyota Camry..." /></Form.Item>
          <Form.Item name="color" label="Màu"><Input /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
