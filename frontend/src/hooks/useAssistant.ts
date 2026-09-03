import { useMutation, useQuery } from "@tanstack/react-query";

import { assistantApi, type ChatMessage } from "@/api/assistant";

export function useAssistantStatus() {
  return useQuery({
    queryKey: ["assistant", "status"],
    queryFn: assistantApi.status,
    // short — so switching provider / adding a key in .env shows up on the
    // next panel open without a hard refresh
    staleTime: 15_000,
    refetchOnWindowFocus: true,
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
