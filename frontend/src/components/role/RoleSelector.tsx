import { useRoleStore } from "../../store/roleStore";

const ROLES = [
  "日系动漫型", "高冷御姐型", "傲娇辣妹型",
  "甜美校花型", "软萌可爱型", "温柔贤淑型",
  "元气少女型", "清冷仙气型",
];

export default function RoleSelector() {
  const { selectedRole, setRole } = useRoleStore();

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-500">角色:</span>
      <select
        value={selectedRole ?? ""}
        onChange={(e) => setRole(e.target.value)}
        className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm focus:border-pink-400 focus:outline-none"
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
    </div>
  );
}
