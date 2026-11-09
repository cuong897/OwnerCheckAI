import { Layout, Avatar, Dropdown, Space, Switch, Typography } from "antd";
import { UserOutlined, LogoutOutlined, EyeInvisibleOutlined, EyeOutlined } from "@ant-design/icons";
import { Outlet, Navigate } from "react-router-dom";
import Sidebar from "@/components/Sidebar";
import RealtimeClock from "@/components/RealtimeClock";
import { usePrivacy } from "@/context/PrivacyContext";
import { useBlacklistSSE } from "@/hooks/useBlacklistSSE";
import { useAuth } from "@/hooks/useAuth";

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

export default function MainLayout() {
  const { username, role, isAuthenticated, isAdmin, logout } = useAuth();

  // SSE listener — chỉ admin nhận BLACKLIST alert
  useBlacklistSSE(isAdmin);

  const { blurOwnerInfo, setBlurOwnerInfo } = usePrivacy();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  const dropdownItems = {
    items: [
      {
        key: "logout",
        label: "Đăng xuất",
        icon: <LogoutOutlined />,
        danger: true,
        onClick: logout,
      },
    ],
  };

  return (
    <Layout style={{ minHeight: "100vh", background: "var(--bg-gradient)" }}>
      <Sider
        width={260}
        style={{
          background: "rgba(10, 15, 28, 0.95)",
          borderRight: "1px solid rgba(255, 255, 255, 0.08)",
        }}
      >
        <Sidebar />
      </Sider>
      <Layout>
        <Header
          className="glass-panel"
          style={{
            height: 70,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 24px",
            zIndex: 10,
          }}
        >
          <RealtimeClock />

          <Space size="large">
            {isAdmin && (
              <Space>
                <Text type="secondary" style={{ fontSize: "13px" }}>
                  Ẩn thông tin cá nhân PII:
                </Text>
                <Switch
                  checked={blurOwnerInfo}
                  onChange={setBlurOwnerInfo}
                  checkedChildren={<EyeInvisibleOutlined />}
                  unCheckedChildren={<EyeOutlined />}
                  style={{ background: blurOwnerInfo ? "#00f2fe" : "#595959" }}
                />
              </Space>
            )}

            <Dropdown menu={dropdownItems} trigger={["click"]}>
              <Space style={{ cursor: "pointer" }}>
                <Avatar icon={<UserOutlined />} style={{ backgroundColor: "#00f2fe", color: "#05060a" }} />
                <div style={{ display: "flex", flexDirection: "column", lineHeight: 1.2 }}>
                  <Text strong style={{ color: "#fff", fontSize: "13px" }}>
                    {username}
                  </Text>
                  <Text type="secondary" style={{ fontSize: "10px", textTransform: "uppercase" }}>
                    {role === "ADMIN" ? "Quản trị viên" : "Người dùng"}
                  </Text>
                </div>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ padding: "30px", overflowY: "auto" }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
