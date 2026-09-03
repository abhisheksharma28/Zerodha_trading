import { useMutation, useQuery } from "@tanstack/react-query";

import { strategyEditorApi, type EditorBacktestBody } from "@/api/strategyEditor";

export function useEditorStarter() {
  return useQuery({
    queryKey: ["strategy-editor", "starter"],
    queryFn: strategyEditorApi.starter,
    staleTime: Infinity,
  });
}

export function useValidateStrategy() {
  return useMutation({
    mutationFn: (source: string) => strategyEditorApi.validate(source),
  });
}

export function useEditorBacktest() {
  return useMutation({
    mutationFn: (body: EditorBacktestBody) => strategyEditorApi.backtest(body),
  });
}

export function useSaveEditorStrategy() {
  return useMutation({
    mutationFn: strategyEditorApi.save,
  });
}
