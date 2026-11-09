import { Card, Row, Col, Statistic, Spin } from "antd";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
} from "recharts";
import { DashboardOutlined, VideoCameraOutlined, AlertOutlined, CarOutlined, UserOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

interface Summary {
  total_logs: number;
  total_cameras: number;
  active_cameras: number;
  total_vehicles: number;
  blacklist_count: number;
  whitelist_count: number;
  vehicles_in_watchlist: number;
}

interface DailyItem {
  date: string;
  total: number;
  success: number;
  failed: number;
  pending: number;
}

interface TopPlate {
  plate_text: string;
  count: number;
}

interface CameraActivity {
  camera_id: number;
  camera_name: string;
  total: number;
}

export default function Dashboard() {
  const summaryQuery = useQuery({
    queryKey: ["stats-summary"],
    queryFn: async () => (await api.get<Summary>("/stats/summary")).data,
    refetchInterval: 15_000,
  });

  const dailyQuery = useQuery({
    queryKey: ["stats-daily"],
    queryFn: async () => (await api.get<DailyItem[]>("/stats/daily?days=7")).data,
  });

  const topQuery = useQuery({
    queryKey: ["stats-top"],
    queryFn: async () => (await api.get<TopPlate[]>("/stats/top-plates?limit=10")).data,
  });

  const cameraQuery = useQuery({
    queryKey: ["stats-camera"],
    queryFn: async () => (await api.get<CameraActivity[]>("/stats/camera-activity?days=7")).data,
  });

  const s = summaryQuery.data;

  // "Bình thường" = vehicle đã đăng ký NHƯNG không nằm trong bất kỳ watchlist nào.
  // Dùng vehicles_in_watchlist (distinct plate) thay vì cộng 2 count — tránh
  // trừ 2 lần khi 1 biển nằm cả trong BLACKLIST lẫn WHITELIST.
  const watchlistPie = s
    ? [
        { name: "Bình thường", value: Math.max(0, s.total_vehicles - s.vehicles_in_watchlist), color: "#52c41a" },
        { name: "Blacklist", value: s.blacklist_count, color: "#ff4d4f" },
        { name: "Whitelist", value: s.whitelist_count, color: "#1890ff" },
      ]
    : [];

  const cameraStatusPie = s
    ? [
        { name: "Hoạt động", value: s.active_cameras, color: "#00f2fe" },
        { name: "Tắt", value: Math.max(0, s.total_cameras - s.active_cameras), color: "#ff4d4f" },
      ]
    : [];

  return (
    <div>
      <Row gutter={[24, 24]} style={{ marginBottom: 24 }}>
        <Col xs={12} lg={6}>
          <Card className="glass-card">
            <Statistic
              title={<span style={{ color: "#8c8c8c" }}>Tổng lượt nhận diện</span>}
              value={s?.total_logs ?? 0}
              valueStyle={{ color: "#00f2fe", fontWeight: 700 }}
              prefix={<DashboardOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card className="glass-card">
            <Statistic
              title={<span style={{ color: "#8c8c8c" }}>Xe đăng ký</span>}
              value={s?.total_vehicles ?? 0}
              valueStyle={{ color: "#52c41a", fontWeight: 700 }}
              prefix={<CarOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card className="glass-card">
            <Statistic
              title={<span style={{ color: "#8c8c8c" }}>Camera trực tuyến</span>}
              value={`${s?.active_cameras ?? 0} / ${s?.total_cameras ?? 0}`}
              valueStyle={{ color: "#faad14", fontWeight: 700 }}
              prefix={<VideoCameraOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card className="glass-card">
            <Statistic
              title={<span style={{ color: "#8c8c8c" }}>BLACKLIST active</span>}
              value={s?.blacklist_count ?? 0}
              valueStyle={{ color: "#ff4d4f", fontWeight: 700 }}
              prefix={<AlertOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[24, 24]}>
        <Col xs={24} lg={16}>
          <Card className="glass-card" title={<span style={{ color: "#fff" }}>Nhận diện theo ngày (7 ngày gần nhất)</span>}>
            {dailyQuery.isLoading ? <Spin /> : (
              <div style={{ width: "100%", height: 280 }}>
                <ResponsiveContainer>
                  <AreaChart data={dailyQuery.data || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <defs>
                      <linearGradient id="colorSuccess" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#52c41a" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#52c41a" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="colorFailed" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#ff4d4f" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#ff4d4f" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="date" stroke="#8c8c8c" fontSize={11} />
                    <YAxis stroke="#8c8c8c" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#141a2e", border: "1px solid rgba(255,255,255,0.1)" }} />
                    <Legend />
                    <Area type="monotone" dataKey="success" name="SUCCESS" stroke="#52c41a" fill="url(#colorSuccess)" strokeWidth={2} />
                    <Area type="monotone" dataKey="failed" name="FAILED" stroke="#ff4d4f" fill="url(#colorFailed)" strokeWidth={2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card className="glass-card" title={<span style={{ color: "#fff" }}>Phân loại Watchlist</span>}>
            {summaryQuery.isLoading ? <Spin /> : (
              <div style={{ width: "100%", height: 280 }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={watchlistPie} cx="50%" cy="45%" innerRadius={50} outerRadius={75} paddingAngle={5} dataKey="value">
                      {watchlistPie.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#141a2e", border: "1px solid rgba(255,255,255,0.1)" }} />
                    <Legend verticalAlign="bottom" />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={16}>
          <Card className="glass-card" title={<span style={{ color: "#fff" }}>Hoạt động theo camera (7 ngày)</span>}>
            {cameraQuery.isLoading ? <Spin /> : (
              <div style={{ width: "100%", height: 280 }}>
                <ResponsiveContainer>
                  <BarChart data={cameraQuery.data || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="camera_name" stroke="#8c8c8c" fontSize={11} />
                    <YAxis stroke="#8c8c8c" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#141a2e", border: "1px solid rgba(255,255,255,0.1)" }} />
                    <Bar dataKey="total" fill="#00f2fe" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card className="glass-card" title={<span style={{ color: "#fff" }}>Camera</span>}>
            {summaryQuery.isLoading ? <Spin /> : (
              <div style={{ width: "100%", height: 280 }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie data={cameraStatusPie} cx="50%" cy="45%" innerRadius={50} outerRadius={75} paddingAngle={5} dataKey="value">
                      {cameraStatusPie.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "#141a2e", border: "1px solid rgba(255,255,255,0.1)" }} />
                    <Legend verticalAlign="bottom" />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24}>
          <Card className="glass-card" title={<span style={{ color: "#fff" }}>Top biển số xuất hiện nhiều nhất (30 ngày)</span>}>
            {topQuery.isLoading ? <Spin /> : (
              <div style={{ width: "100%", height: 280 }}>
                <ResponsiveContainer>
                  <BarChart data={topQuery.data || []} layout="vertical" margin={{ left: 60 }}>
                    <XAxis type="number" stroke="#8c8c8c" fontSize={11} />
                    <YAxis type="category" dataKey="plate_text" stroke="#8c8c8c" fontSize={11} width={120} />
                    <Tooltip contentStyle={{ background: "#141a2e", border: "1px solid rgba(255,255,255,0.1)" }} />
                    <Bar dataKey="count" fill="#4facfe" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
