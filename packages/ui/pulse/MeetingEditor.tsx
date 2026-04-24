"use client";
import { useState } from "react";
import { Sparkles } from "lucide-react";
import type { MeetingStructured } from "@aec/types/pulse";
import { Button } from "../primitives/button";
import { Textarea } from "../primitives/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "../primitives/card";
import { ActionItemList } from "./ActionItemList";

export interface MeetingEditorProps {
  initialNotes?: string;
  language?: "vi" | "en";
  structured?: MeetingStructured | null;
  onStructure: (notes: string) => Promise<MeetingStructured>;
  onCreateTask?: (title: string, deadline: string | null) => void;
  onSave?: (notes: string, structured: MeetingStructured | null) => void;
}

export function MeetingEditor({
  initialNotes = "",
  language = "vi",
  structured: initialStructured = null,
  onStructure,
  onCreateTask,
  onSave,
}: MeetingEditorProps) {
  const [notes, setNotes] = useState(initialNotes);
  const [structured, setStructured] = useState<MeetingStructured | null>(
    initialStructured,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleStructure() {
    if (!notes.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await onStructure(notes);
      setStructured(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI structuring failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {language === "vi" ? "Ghi chú cuộc họp" : "Meeting notes"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={16}
            placeholder={
              language === "vi"
                ? "Dán hoặc nhập ghi chú cuộc họp ở đây…"
                : "Paste or type meeting notes here…"
            }
          />
          <div className="flex gap-2">
            <Button
              onClick={handleStructure}
              disabled={!notes.trim() || loading}
            >
              <Sparkles className="mr-1 h-4 w-4" />
              {loading
                ? "Analyzing…"
                : language === "vi"
                  ? "Cấu trúc hóa bằng AI"
                  : "AI Structure"}
            </Button>
            {onSave && (
              <Button
                variant="secondary"
                onClick={() => onSave(notes, structured)}
              >
                {language === "vi" ? "Lưu" : "Save"}
              </Button>
            )}
          </div>
          {error && <p className="text-sm text-rose-600">{error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {language === "vi" ? "Kết quả có cấu trúc" : "Structured output"}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!structured && (
            <p className="text-muted-foreground">
              {language === "vi"
                ? 'Bấm "Cấu trúc hóa" để xem kết quả.'
                : 'Click "AI Structure" to see results.'}
            </p>
          )}
          {structured && (
            <>
              <section>
                <h4 className="font-semibold">Summary</h4>
                <p className="text-muted-foreground">{structured.summary}</p>
              </section>
              {structured.decisions.length > 0 && (
                <section>
                  <h4 className="font-semibold">Decisions</h4>
                  <ul className="list-disc pl-4 text-muted-foreground">
                    {structured.decisions.map((d) => (
                      <li key={d}>{d}</li>
                    ))}
                  </ul>
                </section>
              )}
              {structured.risks.length > 0 && (
                <section>
                  <h4 className="font-semibold">Risks</h4>
                  <ul className="list-disc pl-4 text-muted-foreground">
                    {structured.risks.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </section>
              )}
              <section>
                <h4 className="font-semibold">Action items</h4>
                <ActionItemList
                  items={structured.action_items}
                  onCreateTask={onCreateTask}
                />
              </section>
              {structured.next_meeting && (
                <p className="text-xs text-muted-foreground">
                  Next meeting:{" "}
                  {new Date(structured.next_meeting).toLocaleDateString()}
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
