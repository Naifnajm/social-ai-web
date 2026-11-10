"use client";
/**
 * Session store: the signed-in user, their workspaces and the active one with its role.
 *
 *   const { me, workspace, role, can } = useSession();
 *   if (can("admin")) ...
 */
import { create } from "zustand";
import { api, setApiWorkspace } from "./api";

export type Role = "viewer" | "editor" | "approver" | "admin" | "owner";
const RANK: Record<Role, number> = { viewer: 0, editor: 1, approver: 2, admin: 3, owner: 4 };

export type Me = {
  user: { id: number; email: string; name: string; locale: string; timezone: string; avatar_url?: string | null; is_superadmin: boolean };
  workspaces: { workspace_id: number; workspace_name: string; role: Role }[];
  current_workspace_id: number | null;
};

export type Workspace = {
  id: number;
  name: string;
  slug: string;
  locale: string;
  timezone: string;
  currency: string;
  logo_media_id?: number | null;
  plan_code: string;
  status: string;
};

type SessionState = {
  me: Me | null;
  workspace: Workspace | null;
  role: Role;
  loading: boolean;
  load: () => Promise<Me | null>;
  setMe: (me: Me) => void;
  switchWorkspace: (id: number) => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  clear: () => void;
  can: (role: Role) => boolean;
};

const STORAGE_KEY = "sai.workspace";

function rememberWorkspace(id: number | null) {
  try {
    if (id) window.localStorage.setItem(STORAGE_KEY, String(id));
  } catch {
    /* storage unavailable */
  }
}

function rememberedWorkspace(): number | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value ? Number(value) : null;
  } catch {
    return null;
  }
}

export const useSession = create<SessionState>((set, get) => ({
  me: null,
  workspace: null,
  role: "viewer",
  loading: true,

  async load() {
    try {
      const me = await api.get<Me>("/auth/me");
      get().setMe(me);
      await get().refreshWorkspace();
      return me;
    } catch {
      set({ me: null, workspace: null, loading: false });
      return null;
    }
  },

  setMe(me) {
    const remembered = rememberedWorkspace();
    const id = me.workspaces.some((w) => w.workspace_id === remembered) ? remembered : me.current_workspace_id;
    setApiWorkspace(id);
    set({ me });
  },

  async switchWorkspace(id) {
    setApiWorkspace(id);
    rememberWorkspace(id);
    await get().refreshWorkspace();
  },

  async refreshWorkspace() {
    const data = await api.get<{ workspace: Workspace; role: Role }>("/workspace");
    setApiWorkspace(data.workspace.id);
    rememberWorkspace(data.workspace.id);
    set({ workspace: data.workspace, role: data.role, loading: false });
  },

  clear() {
    setApiWorkspace(null);
    set({ me: null, workspace: null, role: "viewer", loading: false });
  },

  can(role) {
    return RANK[get().role] >= RANK[role];
  },
}));
