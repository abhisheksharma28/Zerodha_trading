import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { notificationsApi, type NotificationConfig } from "@/api/notifications";

const KEY = ["notifications"];

export function useNotificationConfig(refetchMs = 15000) {
  return useQuery({
    queryKey: [...KEY, "config"],
    queryFn: notificationsApi.config,
    refetchInterval: refetchMs,
  });
}

export function useSetNotificationConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<NotificationConfig>) => notificationsApi.setConfig(patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useSendTestNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => notificationsApi.test(),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useDetectTelegramChats() {
  return useMutation({ mutationFn: () => notificationsApi.detectChats() });
}

export function useNotificationLog(refetchMs = 15000) {
  return useQuery({
    queryKey: [...KEY, "log"],
    queryFn: () => notificationsApi.log(30),
    refetchInterval: refetchMs,
  });
}
