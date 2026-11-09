import { useState } from "react";
import { Table, Card, Button, Modal, Form, Input, Select, Switch, Space, Popconfirm, Tag, App as AntdApp } from "antd";
import { UserAddOutlined, EditOutlined, DeleteOutlined, KeyOutlined, UserOutlined } from "@ant-design/icons";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

interface User {
  id: number;
  username: string;
  role: "USER" | "ADMIN";
  is_active: boolean;
  created_at: string;
}

export default function UsersManage() {
  const qc = useQueryClient();
  const { message, modal } = AntdApp.useApp();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();

  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: async () => (await api.get<User[]>("/users?limit=200")).data,
  });

  const createMut = useMutation({
    mutationFn: async (data: any) => (await api.post("/users", data)).data,
    onSuccess: () => {
      message.success("Tạo user thành công");
      qc.invalidateQueries({ queryKey: ["users"] });
      setCreateOpen(false);
      createForm.resetFields();
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Lỗi"),
  });

  const updateMut = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: any }) =>
      (await api.patch(`/users/${id}`, data)).data,
    onSuccess: () => {
      message.success("Cập nhật thành công");
      qc.invalidateQueries({ queryKey: ["users"] });
      setEditing(null);
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Lỗi"),
  });

  const deleteMut = useMutation({
    mutationFn: async (id: number) => api.delete(`/users/${id}`),
    onSuccess: () => {
      message.success("Đã disable user");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err: any) => message.error(err.response?.data?.detail || "Lỗi"),
  });

  const resetPwd = async (user: User) => {
    try {
      const { data } = await api.post(`/users/${user.id}/reset-password`, {});
      modal.success({
        title: `Mật khẩu mới cho ${user.username}`,
        content: (
          <div>
            <p>Sao chép ngay — chỉ hiển thị 1 lần:</p>
            <code style={{ display: "block", padding: 12, background: "#0d111e", fontSize: 16, color: "#00f2fe" }}>
              {data.new_password}
            </code>
          </div>
        ),
        width: 480,
      });
    } catch (err: any) {
      message.error(err.response?.data?.detail || "Lỗi reset");
    }
  };

  const columns: ColumnsType<User> = [
    { title: "ID", dataIndex: "id", width: 60 },
    { title: "Username", dataIndex: "username", render: (t) => <code style={{ color: "#fff" }}>{t}</code> },
    {
      title: "Role",
      dataIndex: "role",
      width: 110,
      render: (r) => <Tag color={r === "ADMIN" ? "gold" : "blue"}>{r === "ADMIN" ? "Quản trị viên" : "Người dùng"}</Tag>,
    },
    {
      title: "Trạng thái",
      dataIndex: "is_active",
      width: 110,
      render: (a) => <Tag color={a ? "green" : "red"}>{a ? "Active" : "Disabled"}</Tag>,
    },
    { title: "Tạo lúc", dataIndex: "created_at", width: 170, render: (t) => dayjs(t).format("DD/MM/YYYY HH:mm") },
    {
      title: "Hành động",
      width: 280,
      render: (_, user) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => { setEditing(user); editForm.setFieldsValue(user); }}>
            Sửa
          </Button>
          <Button size="small" icon={<KeyOutlined />} onClick={() => resetPwd(user)}>
            Reset PW
          </Button>
          <Popconfirm title={`Disable user "${user.username}"?`} onConfirm={() => deleteMut.mutate(user.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} disabled={!user.is_active}>
              Disable
            </Button>
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
          <UserOutlined style={{ color: "#00f2fe", fontSize: 18 }} />
          <span style={{ fontSize: 16, fontWeight: 600, color: "#fff" }}>Quản lý người dùng</span>
        </Space>
        <Button type="primary" icon={<UserAddOutlined />} onClick={() => setCreateOpen(true)}>
          Tạo user mới
        </Button>
      </Card>

      <Card className="glass-card" styles={{ body: { padding: 0 } }}>
        <Table rowKey="id" loading={usersQuery.isLoading} dataSource={usersQuery.data} columns={columns} pagination={{ pageSize: 10 }} />
      </Card>

      {/* Create */}
      <Modal
        open={createOpen}
        title="Tạo user mới"
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={createMut.isPending}
        okText="Tạo"
        cancelText="Hủy"
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={(v) => createMut.mutate(v)}
          initialValues={{ role: "USER", is_active: true }}
        >
          <Form.Item name="username" label="Username" rules={[{ required: true, min: 3 }]}>
            <Input />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true, min: 6 }]}>
            <Input.Password />
          </Form.Item>
          <Form.Item name="role" label="Role">
            <Select options={[{ value: "USER", label: "USER" }, { value: "ADMIN", label: "ADMIN" }]} />
          </Form.Item>
          <Form.Item name="is_active" label="Kích hoạt" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* Edit */}
      <Modal
        open={!!editing}
        title={`Sửa user #${editing?.id}`}
        onCancel={() => setEditing(null)}
        onOk={() => editForm.submit()}
        confirmLoading={updateMut.isPending}
        okText="Lưu"
        cancelText="Hủy"
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(v) => editing && updateMut.mutate({ id: editing.id, data: v })}
        >
          <Form.Item name="role" label="Role">
            <Select options={[{ value: "USER", label: "USER" }, { value: "ADMIN", label: "ADMIN" }]} />
          </Form.Item>
          <Form.Item name="is_active" label="Kích hoạt" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
