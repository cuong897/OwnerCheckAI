import React from "react";
import { Menu, Typography } from "antd";
import { Link, useLocation } from "react-router-dom";
import {
  PlayCircleOutlined,
  HistoryOutlined,
  SearchOutlined,
  DashboardOutlined,
  UserOutlined,
  VideoCameraOutlined,
  CarOutlined,
  AlertOutlined,
} from "@ant-design/icons";
import { useAuth } from "@/hooks/useAuth";

const { Title } = Typography;

const Sidebar: React.FC = () => {
  const location = useLocation();
  const { isAdmin } = useAuth();

  const menuItems: any[] = [
    {
      key: "/live",
      icon: <PlayCircleOutlined />,
      label: <Link to="/live">Giám sát trực tuyến</Link>,
    },
    {
      key: "/history",
      icon: <HistoryOutlined />,
      label: <Link to="/history">Lịch sử ra vào</Link>,
    },
    {
      key: "/lookup",
      icon: <SearchOutlined />,
      label: <Link to="/lookup">Tra cứu thông tin</Link>,
    },
  ];

  if (isAdmin) {
    menuItems.push(
      { key: "admin-divider", type: "divider" },
      {
        key: "/admin/dashboard",
        icon: <DashboardOutlined />,
        label: <Link to="/admin/dashboard">Bảng giám sát</Link>,
      },
      {
        key: "/admin/users",
        icon: <UserOutlined />,
        label: <Link to="/admin/users">Quản lý người dùng</Link>,
      },
      {
        key: "/admin/cameras",
        icon: <VideoCameraOutlined />,
        label: <Link to="/admin/cameras">Quản lý camera</Link>,
      },
      {
        key: "/admin/vehicles",
        icon: <CarOutlined />,
        label: <Link to="/admin/vehicles">Quản lý danh sách xe</Link>,
      },
      {
        key: "/admin/watchlists",
        icon: <AlertOutlined />,
        label: <Link to="/admin/watchlists">Danh sách đen/trắng</Link>,
      }
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ padding: "24px 16px", display: "flex", alignItems: "center", gap: "8px" }}>
        <div
          style={{
            width: "32px",
            height: "32px",
            borderRadius: "6px",
            background: "linear-gradient(135deg, #00f2fe 0%, #4facfe 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: "0 0 10px rgba(0, 242, 254, 0.4)",
          }}
        >
          <span style={{ fontWeight: 800, color: "#05060a", fontSize: "16px" }}>O</span>
        </div>
        <Title
          level={4}
          style={{ margin: 0, fontWeight: 800, letterSpacing: "0.5px" }}
          className="gradient-text-cyan-blue"
        >
          OwnerCheckAI
        </Title>
      </div>

      <Menu
        mode="inline"
        selectedKeys={[location.pathname]}
        items={menuItems}
        style={{ flex: 1, marginTop: "16px" }}
      />
    </div>
  );
};

export default Sidebar;
