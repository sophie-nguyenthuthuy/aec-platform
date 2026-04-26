"use client";

import { useMutation } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useSession } from "@/lib/auth-context";
import type { UUID } from "@aec/types/envelope";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantSource {
  module: string;
  label: string;
  route?: string | null;
}

export interface AssistantResponse {
  project_id: UUID;
  answer: string;
  sources: AssistantSource[];
  context_token_estimate: number;
}

export interface AskRequest {
  question: string;
  history?: ChatTurn[];
}

/** Ask the assistant a question scoped to one project. The mutation owns
 *  the network call; the caller owns the chat-history state and replays
 *  it on each turn (matches the stateless backend contract). */
export function useAskAssistant(projectId: UUID) {
  const { token, orgId } = useSession();
  return useMutation({
    mutationFn: async (req: AskRequest) => {
      const res = await apiFetch<AssistantResponse>(
        `/api/v1/assistant/projects/${projectId}/ask`,
        {
          method: "POST",
          token,
          orgId,
          body: req,
        },
      );
      return res.data as AssistantResponse;
    },
  });
}
