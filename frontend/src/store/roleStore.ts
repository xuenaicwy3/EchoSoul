import { create } from "zustand";

interface RoleState {
  selectedRole: string | null;
  setRole: (role: string) => void;
}

export const useRoleStore = create<RoleState>((set) => ({
  selectedRole: localStorage.getItem("echosoul_role"),
  setRole: (role) => {
    localStorage.setItem("echosoul_role", role);
    set({ selectedRole: role });
  },
}));
