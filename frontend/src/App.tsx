import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider, theme, App as AntdApp } from "antd";
import viVN from "antd/locale/vi_VN";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PrivacyProvider } from "@/context/PrivacyContext";
import { ProtectedRoute } from "@/routes/ProtectedRoute";

import AuthLayout from "@/layouts/AuthLayout";
import MainLayout from "@/layouts/MainLayout";

import Login from "@/pages/Login";
import LiveView from "@/pages/LiveView";
import HistoryLogs from "@/pages/HistoryLogs";
import Lookup from "@/pages/Lookup";

import Dashboard from "@/pages/Dashboard";
import UsersManage from "@/pages/UsersManage";
import CamerasManage from "@/pages/CamerasManage";
import VehiclesManage from "@/pages/VehiclesManage";
import WatchlistsManage from "@/pages/WatchlistsManage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

export default function App() {
  return (
    <ConfigProvider
      locale={viVN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#00f2fe",
          colorInfo: "#4facfe",
          borderRadius: 8,
          fontFamily: "Outfit, Inter, sans-serif",
        },
      }}
    >
      <AntdApp>
        <QueryClientProvider client={queryClient}>
          <PrivacyProvider>
            <BrowserRouter>
              <Routes>
                {/* Auth */}
                <Route element={<AuthLayout />}>
                  <Route path="/login" element={<Login />} />
                </Route>

                {/* User routes (any authenticated) */}
                <Route
                  element={
                    <ProtectedRoute>
                      <MainLayout />
                    </ProtectedRoute>
                  }
                >
                  <Route path="/" element={<Navigate to="/live" replace />} />
                  <Route path="/live" element={<LiveView />} />
                  <Route path="/history" element={<HistoryLogs />} />
                  <Route path="/lookup" element={<Lookup />} />

                  {/* Admin routes */}
                  <Route
                    path="/admin/dashboard"
                    element={
                      <ProtectedRoute adminOnly>
                        <Dashboard />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/admin/users"
                    element={
                      <ProtectedRoute adminOnly>
                        <UsersManage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/admin/cameras"
                    element={
                      <ProtectedRoute adminOnly>
                        <CamerasManage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/admin/vehicles"
                    element={
                      <ProtectedRoute adminOnly>
                        <VehiclesManage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/admin/watchlists"
                    element={
                      <ProtectedRoute adminOnly>
                        <WatchlistsManage />
                      </ProtectedRoute>
                    }
                  />
                </Route>

                <Route path="*" element={<Navigate to="/live" replace />} />
              </Routes>
            </BrowserRouter>
          </PrivacyProvider>
        </QueryClientProvider>
      </AntdApp>
    </ConfigProvider>
  );
}
