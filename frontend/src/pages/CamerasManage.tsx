import { useState } from "react";
import { Table, Card, Button, Modal, Form, Input, Select, Space, Popconfirm, Tag, App as AntdApp } from "antd";
import { VideoCameraAddOutlined, EditOutlined, DeleteOutlined, VideoCameraOutlined } from "@ant-design/icons";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ColumnsType } from "antd/es/table";

interface Camera {
  id: number;
  camera_name: string;
  location: string | null;
  rtsp_url: string | null;
  status: "ACTIVE" | "INACTIVE";
}

export default function CamerasManage() {
  const qc = useQueryClient();
  const { message } = AntdApp.useApp();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Camera | null>(null);
  const [form] = Form.useForm();

  const query = useQuery({
    queryKey: ["cameras-admin"],
    queryFn: async () => (await api.get<Camera[]>("/cameras?limit=200")).data,
  });

  const upsertMut = useMutation({
    mutationFn: async (data: any) =>
      editing
        ? (await api.patch(`/cameras/${editing.id}`, data)).data
        : (await api.post("/cameras", data)).data,
    onSuccess: () => {
      message.success(editing ? "Cập nhật thành công" : "Thêm camera thành công");
      qc.invalidateQueries({ queryKey: ["cameras-admin"] });
      setOpen(false);
      setEditing(null);
      form.resetFields();
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Lỗi"),
  });

  const deleteMut = useMutation({
    mutationFn: async (id: number) => api.delete(`/cameras/${id}`),
    onSuccess: () => {
      message.success("Đã xoá");
      qc.invalidateQueries({ queryKey: ["cameras-admin"] });
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Xoá thất bại"),
  });

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ status: "ACTIVE" });
    setOpen(true);
  };

  const openEdit = (cam: Camera) => {
    setEditing(cam);
    form.setFieldsValue(cam);
    setOpen(true);
  };

  const columns: ColumnsType<Camera> = [
    { title: "ID", dataIndex: "id", width: 60 },
    { title: "Tên", dataIndex: "camera_name", render: (t) => <span style={{ color: "#fff", fontWeight: 600 }}>{t}</span> },
    { title: "Vị trí", dataIndex: "location" },
    { title: "RTSP URL", dataIndex: "rtsp_url", ellipsis: true, render: (t) => <code style={{ color: "#00f2fe" }}>{t || "-"}</code> },
    {
      title: "Trạng thái",
      dataIndex: "status",
      width: 130,
      render: (s) => <Tag color={s === "ACTIVE" ? "green" : "default"}>{s}</Tag>,
    },
    {
      title: "Hành động",
      width: 180,
      render: (_, cam) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(cam)}>Sửa</Button>
          <Popconfirm title="Xoá camera?" onConfirm={() => deleteMut.mutate(cam.id)}>
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
          <VideoCameraOutlined style={{ color: "#00f2fe", fontSize: 18 }} />
          <span style={{ fontSize: 16, fontWeight: 600, color: "#fff" }}>Quản lý Camera (RTSP)</span>
        </Space>
        <Button type="primary" icon={<VideoCameraAddOutlined />} onClick={openCreate}>
          Thêm camera
        </Button>
      </Card>

      <Card className="glass-card" styles={{ body: { padding: 0 } }}>
        <Table rowKey="id" loading={query.isLoading} dataSource={query.data} columns={columns} pagination={false} />
      </Card>

      <Modal
        open={open}
        title={editing ? `Sửa camera #${editing.id}` : "Thêm camera mới"}
        onCancel={() => { setOpen(false); setEditing(null); form.resetFields(); }}
        onOk={() => form.submit()}
        confirmLoading={upsertMut.isPending}
        okText="Lưu"
        cancelText="Hủy"
      >
        <Form form={form} layout="vertical" onFinish={(v) => upsertMut.mutate(v)}>
          <Form.Item name="camera_name" label="Tên camera" rules={[{ required: true }]}>
            <Input placeholder="VD: Cổng vào" />
          </Form.Item>
          <Form.Item name="location" label="Vị trí">
            <Input placeholder="VD: Tầng hầm B1" />
          </Form.Item>
          <Form.Item name="rtsp_url" label="RTSP URL">
            <Input placeholder="rtsp://user:pass@host:554/stream" />
          </Form.Item>
          <Form.Item name="status" label="Trạng thái">
            <Select options={[
              { value: "ACTIVE", label: "ACTIVE" },
              { value: "INACTIVE", label: "INACTIVE" },
            ]} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
