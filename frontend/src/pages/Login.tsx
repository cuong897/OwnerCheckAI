import { useState } from "react";
import { Card, Form, Input, Button, Typography, App as AntdApp } from "antd";
import { UserOutlined, LockOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { login } from "@/hooks/useAuth";

const { Title, Text } = Typography;

export default function Login() {
  const navigate = useNavigate();
  const { message } = AntdApp.useApp();
  const [loading, setLoading] = useState(false);

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const user = await login(values.username, values.password);
      message.success(`Đăng nhập thành công! Xin chào ${user.username}`);
      navigate(user.role === "ADMIN" ? "/admin/dashboard" : "/live", { replace: true });
    } catch (err: any) {
      message.error(err.response?.data?.detail || "Sai tài khoản hoặc mật khẩu");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card
      className="glass-card"
      style={{ width: 400, padding: "24px 12px", border: "1px solid rgba(0, 242, 254, 0.2)" }}
      styles={{ body: { display: "flex", flexDirection: "column", gap: "16px" } }}
    >
      <div style={{ textAlign: "center", marginBottom: "12px" }}>
        <SafetyCertificateOutlined style={{ fontSize: "48px", color: "#00f2fe", marginBottom: "12px" }} />
        <Title level={2} style={{ margin: 0, fontWeight: 800 }} className="gradient-text-cyan-blue">
          OwnerCheckAI
        </Title>
        <Text type="secondary" style={{ fontSize: "13px" }}>
          Hệ thống nhận diện biển số & tra cứu chủ xe ANPR
        </Text>
      </div>

      <Form name="login_form" onFinish={onFinish} layout="vertical" size="large" disabled={loading}>
        <Form.Item name="username" rules={[{ required: true, message: "Vui lòng nhập tài khoản!" }]}>
          <Input
            prefix={<UserOutlined style={{ color: "rgba(255,255,255,0.25)" }} />}
            placeholder="Tài khoản"
            autoFocus
            style={{ background: "rgba(0,0,0,0.2)", color: "#fff", border: "1px solid rgba(255,255,255,0.12)" }}
          />
        </Form.Item>

        <Form.Item name="password" rules={[{ required: true, message: "Vui lòng nhập mật khẩu!" }]}>
          <Input.Password
            prefix={<LockOutlined style={{ color: "rgba(255,255,255,0.25)" }} />}
            placeholder="Mật khẩu"
            style={{ background: "rgba(0,0,0,0.2)", color: "#fff", border: "1px solid rgba(255,255,255,0.12)" }}
          />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} style={{ width: "100%", marginTop: "8px" }}>
            Đăng nhập
          </Button>
        </Form.Item>

        <Text type="secondary" style={{ fontSize: 12 }}>
          Demo: <code>admin / admin123</code> (đăng ký qua POST /auth/register)
        </Text>
      </Form>
    </Card>
  );
}
