"use client";
import { TemplateManager } from "@aec/ui/winwork/TemplateManager";

export default function TemplatesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Templates</h1>
        <p className="text-sm text-muted-foreground">Reusable proposal templates.</p>
      </div>
      <TemplateManager templates={[]} />
    </div>
  );
}
