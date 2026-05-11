"use client";
import type { ProposalTemplate } from "@aec/types/winwork";

import { Badge } from "../primitives/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";

interface TemplateManagerProps {
  templates: ProposalTemplate[];
  onSelect?: (template: ProposalTemplate) => void;
}

export function TemplateManager({ templates, onSelect }: TemplateManagerProps) {
  if (templates.length === 0) {
    return (
      <Card>
        <CardContent className="p-8 text-center text-sm text-muted-foreground">
          Chưa có mẫu nào. Tạo từ đề xuất hiện có bằng menu ⋯.
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="grid grid-cols-2 gap-4">
      {templates.map((t) => (
        <Card key={t.id} className="cursor-pointer hover:bg-muted/40" onClick={() => onSelect?.(t)}>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">{t.name}</CardTitle>
              {t.is_default && <Badge variant="secondary">Mặc định</Badge>}
            </div>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <div>Bộ môn: {t.discipline ?? "tất cả"}</div>
            {t.project_types.length > 0 && <div>Loại dự án: {t.project_types.join(", ")}</div>}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
