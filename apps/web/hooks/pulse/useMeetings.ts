"use client";
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";
import type {
  MeetingNote,
  MeetingNoteCreate,
  MeetingStructureRequest,
} from "@aec/types/pulse";
import { apiFetch } from "../../lib/api";
import { useSession } from "../../lib/auth-context";
import { pulseKeys } from "./keys";

export function useCreateMeetingNote(): UseMutationResult<
  MeetingNote,
  Error,
  MeetingNoteCreate
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const res = await apiFetch<MeetingNote>("/api/v1/pulse/meeting-notes", {
        method: "POST",
        token,
        orgId,
        body: input,
      });
      if (!res.data) throw new Error("Create meeting note failed");
      return res.data;
    },
    onSuccess: (note) => {
      qc.invalidateQueries({
        queryKey: pulseKeys.meetingNotes(note.project_id),
      });
    },
  });
}

export function useStructureMeetingNotes(): UseMutationResult<
  MeetingNote,
  Error,
  MeetingStructureRequest
> {
  const { token, orgId } = useSession();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input) => {
      const res = await apiFetch<MeetingNote>(
        "/api/v1/pulse/meeting-notes/structure",
        { method: "POST", token, orgId, body: input },
      );
      if (!res.data) throw new Error("Structure meeting notes failed");
      return res.data;
    },
    onSuccess: (note) => {
      qc.invalidateQueries({
        queryKey: pulseKeys.meetingNotes(note.project_id),
      });
    },
  });
}
