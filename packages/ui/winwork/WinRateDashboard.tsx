"use client";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { WinRateAnalytics } from "@aec/types/winwork";

import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";

function fmtVND(n: number): string {
  return new Intl.NumberFormat("vi-VN", { notation: "compact" }).format(n) + " ₫";
}

export function WinRateDashboard({ data }: { data: WinRateAnalytics }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-4">
        <Kpi label="Tổng" value={String(data.total)} />
        <Kpi label="Tỷ lệ thắng" value={`${Math.round(data.win_rate * 100)}%`} />
        <Kpi label="Phí TB" value={fmtVND(data.avg_fee_vnd)} />
        <Kpi label="Đang chờ" value={String(data.pending)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Tỷ lệ thắng theo loại dự án</CardTitle>
        </CardHeader>
        <CardContent className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.by_project_type}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="project_type" />
              <YAxis />
              <Tooltip formatter={(v: number, name: string) => (name === "win_rate" ? `${Math.round(v * 100)}%` : v)} />
              <Legend />
              <Bar dataKey="total" fill="#94a3b8" name="Tổng" />
              <Bar dataKey="won" fill="#16a34a" name="Thắng" />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Xu hướng theo tháng</CardTitle>
        </CardHeader>
        <CardContent className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data.by_month}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="month" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line dataKey="total" stroke="#94a3b8" name="Total" />
              <Line dataKey="won" stroke="#16a34a" name="Won" />
              <Line dataKey="lost" stroke="#dc2626" name="Lost" />
            </LineChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs uppercase text-muted-foreground">{label}</div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}
