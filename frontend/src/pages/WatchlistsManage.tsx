import { useState } from "react";
import { Table, Card, Button, Modal, Form, Input, Select, Space, Popconfirm, Tag, App as AntdApp } from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined, AlertOutlined } from "@ant-design/icons";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ColumnsType } from "antd/es/table";

interface Watch {
  id: number;
  plate_number: string;
  category: "BLACKLIST" | "WHITELIST";
  owner_name: string | null;
  note: string | null;
}

export default function WatchlistsManage() {
  const qc = useQueryClient();
  const { message } = AntdApp.useApp();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Watch | null>(null);
  const [form] = Form.useForm();

  const query = useQuery({
    queryKey: ["watchlists-admin"],
    queryFn: async () => (await api.get<Watch[]>("/watchlists?limit=500")).data,
  });

  const upsertMut = useMutation({
    mutationFn: async (data: any) => {
      const payload = { ...data, plate_number: data.plate_number?.toUpperCase() };
      return editing
        ? (await api.patch(`/watchlists/${editing.id}`, payload)).data
        : (await api.post("/watchlists", payload)).data;
    },
    onSuccess: () => {
      message.success(editing ? "Cập nhật" : "Đã thêm");
      qc.invalidateQueries({ queryKey: ["watchlists-admin"] });
      setOpen(false);
      setEditing(null);
      form.resetFields();
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Lỗi"),
  });

  const deleteMut = useMutation({
    mutationFn: async (id: number) => api.delete(`/watchlists/${id}`),
    onSuccess: () => {
      message.success("Đã xoá");
      qc.invalidateQueries({ queryKey: ["watchlists-admin"] });
    },
  });

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ category: "BLACKLIST" });
    setOpen(true);
  };

  const openEdit = (w: Watch) => {
    setEditing(w);
    form.setFieldsValue(w);
    setOpen(true);
  };

  const columns: ColumnsType<Watch> = [
    { title: "ID", dataIndex: "id", width: 60 },
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
      title: "Danh sách",
      dataIndex: "category",
      width: 150,
      render: (c) => <Tag color={c === "BLACKLIST" ? "error" : "success"}>{c}</Tag>,
    },
    { title: "Chủ xe", dataIndex: "owner_name", width: 180 },
    { title: "Ghi chú", dataIndex: "note" },
    {
      title: "Hành động",
      width: 180,
      render: (_, w) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(w)}>Sửa</Button>
          <Popconfirm title="Xoá entry?" onConfirm={() => deleteMut.mutate(w.id)}>
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
        styles={{ body: { display: "flex", justifyContent: "space-between", alignItems: "center" } }}
      >
        <Space>
          <AlertOutlined style={{ color: "#00f2fe", fontSize: 18 }} />
          <span style={{ fontSize: 16, fontWeight: 600, color: "#fff" }}>Watchlist (BLACKLIST / WHITELIST)</span>
        </Space>
        <Button type="primary" danger icon={<PlusOutlined />} onClick={openCreate}>
          Thêm entry
        </Button>
      </Card>

      <Card className="glass-card" styles={{ body: { padding: 0 } }}>
        <Table rowKey="id" loading={query.isLoading} dataSource={query.data} columns={columns} pagination={{ pageSize: 10 }} />
      </Card>

      <Modal
        open={open}
        title={editing ? `Sửa entry #${editing.id}` : "Thêm vào watchlist"}
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
          <Form.Item name="category" label="Danh sách" rules={[{ required: true }]}>
            <Select options={[
              { value: "BLACKLIST", label: "BLACKLIST" },
              { value: "WHITELIST", label: "WHITELIST" },
            ]} />
          </Form.Item>
          <Form.Item
            name="owner_name"
            label="Chủ xe"
            extra="Bắt buộc nếu biển số chưa có trong danh sách xe (hệ thống sẽ tự tạo)."
          >
            <Input placeholder="Nguyễn Văn A" />
          </Form.Item>
          <Form.Item name="note" label="Ghi chú">
            <Input.TextArea rows={3} placeholder="Lý do thêm vào watchlist..." />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
