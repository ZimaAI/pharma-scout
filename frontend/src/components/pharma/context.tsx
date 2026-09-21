"use client";

import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

import {
  pharmaFetch,
  PharmaAPIError,
  type RequestOptions,
} from "@/core/pharma/client";
import {
  type Me,
  type Membership,
  type WorkspaceConfiguration,
} from "@/core/pharma/contracts";

type PharmaContextValue = {
  me: Me;
  workspaceId: string;
  workspace: Membership;
  config: WorkspaceConfiguration | undefined;
  request: <T>(path: string, options?: RequestOptions) => Promise<T>;
  refresh: () => Promise<void>;
};
const Context = createContext<PharmaContextValue | null>(null);
const EvidenceContext = createContext<(id: string) => void>(() => undefined);

export function PharmaQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            staleTime: 15_000,
            refetchOnWindowFocus: true,
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

export function WorkspaceProvider({
  me,
  workspace,
  children,
  openEvidence,
}: {
  me: Me;
  workspace: Membership;
  children: ReactNode;
  openEvidence: (id: string) => void;
}) {
  const client = useQueryClient();
  const router = useRouter();
  const request = useCallback(
    async <T,>(path: string, options?: RequestOptions): Promise<T> => {
      try {
        return await pharmaFetch<T>(
          `/workspaces/${workspace.workspace_id}${path}`,
          options,
          me.csrf_token,
        );
      } catch (error) {
        if (error instanceof PharmaAPIError && error.status === 401) {
          client.clear();
          router.replace("/pharma/login");
        }
        throw error;
      }
    },
    [workspace.workspace_id, me.csrf_token, client, router],
  );
  const configuration = useQuery({
    queryKey: ["pharma", workspace.workspace_id, "/configuration"],
    queryFn: ({ signal }) =>
      request<WorkspaceConfiguration>("/configuration", { signal }),
  });
  const refresh = useCallback(async () => {
    await client.invalidateQueries({
      queryKey: ["pharma", workspace.workspace_id],
    });
  }, [client, workspace.workspace_id]);
  return (
    <Context.Provider
      value={{
        me,
        workspaceId: workspace.workspace_id,
        workspace,
        config: configuration.data,
        request,
        refresh,
      }}
    >
      <EvidenceContext.Provider value={openEvidence}>
        {children}
      </EvidenceContext.Provider>
    </Context.Provider>
  );
}

export function usePharma() {
  const context = useContext(Context);
  if (!context) throw new Error("Pharma workspace provider is required");
  return context;
}

export function useResource<T>(path: string | null, interval?: number) {
  const { workspaceId, request } = usePharma();
  return useQuery({
    queryKey: ["pharma", workspaceId, path],
    queryFn: ({ signal }) => request<T>(path!, { signal }),
    enabled: path !== null,
    refetchInterval: interval,
  });
}

export function useEvidence() {
  return useContext(EvidenceContext);
}
