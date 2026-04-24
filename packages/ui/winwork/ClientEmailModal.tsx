"use client";
import { useState } from "react";
import { Button } from "../primitives/button";
import { Dialog } from "../primitives/dialog";
import { Input } from "../primitives/input";
import { Label } from "../primitives/label";
import { Textarea } from "../primitives/textarea";

interface ClientEmailModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultSubject?: string;
  onSend: (payload: { subject: string; message: string; cc: string[] }) => Promise<void> | void;
  sending?: boolean;
}

export function ClientEmailModal({ open, onOpenChange, defaultSubject = "", onSend, sending }: ClientEmailModalProps) {
  const [subject, setSubject] = useState(defaultSubject);
  const [message, setMessage] = useState("");
  const [cc, setCc] = useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Send proposal">
      <div className="space-y-4">
        <div className="space-y-1">
          <Label>Subject</Label>
          <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>Message</Label>
          <Textarea rows={5} value={message} onChange={(e) => setMessage(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label>CC (comma-separated)</Label>
          <Input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="ops@firm.com, lead@firm.com" />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={sending}>
            Cancel
          </Button>
          <Button
            onClick={async () => {
              await onSend({
                subject,
                message,
                cc: cc.split(",").map((s) => s.trim()).filter(Boolean),
              });
              onOpenChange(false);
            }}
            disabled={sending}
          >
            {sending ? "Sending…" : "Send"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
