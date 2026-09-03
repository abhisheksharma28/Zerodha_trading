import { useMutation, useQuery } from "@tanstack/react-query";

import { assistantApi, type ChatMessage } from "@/api/assistant";

export function useAssistantStatus() {
  return useQuery({
    queryKey: ["assistant", "status"],
    queryFn: assistantApi.status,
    staleTime: 5 * 60_000,
  });
}

export function useAssistantSuggestions() {
  return useQuery({
    queryKey: ["assistant", "suggestions"],
    queryFn: assistantApi.suggestions,
    staleTime: Infinity,
  });
}

export function useAssistantChat() {
  return useMutation({
    mutationFn: (messages: ChatMessage[]) => assistantApi.chat(messages),
  });
}
