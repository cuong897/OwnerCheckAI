import React, { useState, useEffect } from "react";
import { Typography } from "antd";
import { ClockCircleOutlined } from "@ant-design/icons";

const { Text } = Typography;

const RealtimeClock: React.FC = () => {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const formatTime = (date: Date) => {
    const hh = String(date.getHours()).padStart(2, "0");
    const mm = String(date.getMinutes()).padStart(2, "0");
    const ss = String(date.getSeconds()).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const MM = String(date.getMonth() + 1).padStart(2, "0");
    const yyyy = date.getFullYear();
    return `${hh}:${mm}:${ss} - ${dd}/${MM}/${yyyy}`;
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <ClockCircleOutlined style={{ color: "#00f2fe", fontSize: "15px" }} />
      <Text style={{ color: "#00f2fe", fontFamily: "monospace", fontSize: "14px", fontWeight: 600 }}>
        {formatTime(time)}
      </Text>
    </div>
  );
};

export default RealtimeClock;
