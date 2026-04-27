"use client";

import { useState } from "react";
import { Trash2, UserPlus } from "lucide-react";

import {
  type OrgMember,
  type Role,
  useInviteMember,
  useOrgMembers,
  useRemoveMember,
  useUpdateMemberRole,
} from "@/hooks/org";


const ROLES: Array<{ value: Role; label: string; help: string }> = [
  { value: "viewer",  label: "Viewer",  help: "Read-only across modules" },
  { value: "member",  label: "Member",  help: "Read + write within modules" },
  { value: "admin",   label: "Admin",   help: "Full read/write + manage members" },
  { value: "owner",   label: "Owner",   help: "Admin + billing + delete org" },
];

const ROLE_BADGE: Record<Role, string> = {
  owner:  "bg-rose-100 text-rose-800",
  admin:  "bg-indigo-100 text-indigo-800",
  member: "bg-blue-100 text-blue-800",
  viewer: "bg-slate-100 text-slate-700",
};

export default function MembersPage() {
  const { data: members, isLoading, error } = useOrgMembers();
  const invite = useInviteMember();
  const updateRole = useUpdateMemberRole();
  const removeMember = useRemoveMember();

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("member");

  const handleInvite = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    invite.mutate(
      { email: inviteEmail.trim(), role: inviteRole },
      {
        onSuccess: () => {
          setInviteEmail("");
          setInviteRole("member");
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">Thành viên</h2>
        <p className="text-sm text-slate-600">
          Quản lý quyền truy cập của thành viên trong tổ chức.
        </p>
      </div>

      {/* ---------------- Invite form (admin/owner only) ---------------- */}
      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded bg-indigo-100 text-indigo-700">
            <UserPlus size={14} />
          </span>
          <h3 className="text-sm font-semibold text-slate-900">Mời thành viên</h3>
        </div>
        <form
          onSubmit={handleInvite}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="flex-1 min-w-[260px]">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Email
            </label>
            <input
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="newuser@example.com"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Vai trò
            </label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as Role)}
              className="mt-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none"
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            disabled={invite.isPending || !inviteEmail.trim()}
            className="rounded-md bg-indigo-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {invite.isPending ? "Đang mời..." : "Gửi lời mời"}
          </button>
        </form>
        {invite.isError && (
          <p className="mt-2 text-xs text-red-600">
            {(invite.error as Error)?.message ?? "Mời thất bại"}
          </p>
        )}
        <p className="mt-2 text-xs text-slate-500">
          Hệ thống sẽ tạo bản ghi user nếu email chưa từng đăng nhập. Người
          dùng cần có tài khoản Supabase trước khi truy cập được vào tổ chức.
        </p>
      </section>

      {/* ---------------- Members list ---------------- */}
      <section className="rounded-xl border border-slate-200 bg-white">
        <header className="border-b border-slate-100 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-900">
            Danh sách thành viên
          </h3>
        </header>

        {isLoading ? (
          <p className="px-5 py-8 text-sm text-slate-500">Đang tải...</p>
        ) : error ? (
          <p className="px-5 py-8 text-sm text-red-600">
            Không thể tải danh sách thành viên.
          </p>
        ) : !members || members.length === 0 ? (
          <p className="px-5 py-8 text-sm text-slate-500">Chưa có thành viên nào.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {members.map((m) => (
              <MemberRow
                key={m.membership_id}
                member={m}
                onRoleChange={(role) =>
                  updateRole.mutate({ user_id: m.user_id, role })
                }
                onRemove={() => {
                  if (
                    window.confirm(
                      `Xóa ${m.email} khỏi tổ chức? Hành động này không thể hoàn tác.`,
                    )
                  ) {
                    removeMember.mutate(m.user_id);
                  }
                }}
                rolePending={
                  updateRole.isPending && updateRole.variables?.user_id === m.user_id
                }
                removePending={
                  removeMember.isPending && removeMember.variables === m.user_id
                }
              />
            ))}
          </ul>
        )}

        {(updateRole.isError || removeMember.isError) && (
          <div className="border-t border-red-100 bg-red-50 px-5 py-2 text-xs text-red-700">
            {(updateRole.error as Error)?.message ??
              (removeMember.error as Error)?.message}
          </div>
        )}
      </section>
    </div>
  );
}


function MemberRow({
  member,
  onRoleChange,
  onRemove,
  rolePending,
  removePending,
}: {
  member: OrgMember;
  onRoleChange: (role: Role) => void;
  onRemove: () => void;
  rolePending: boolean;
  removePending: boolean;
}) {
  return (
    <li className="flex items-center gap-4 px-5 py-3">
      <div className="flex flex-1 items-center gap-3 min-w-0">
        <Avatar name={member.full_name ?? member.email} src={member.avatar_url} />
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-900">
            {member.full_name ?? member.email}
          </p>
          {member.full_name && (
            <p className="truncate text-xs text-slate-500">{member.email}</p>
          )}
        </div>
      </div>

      <span
        className={`hidden shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium md:inline-flex ${ROLE_BADGE[member.role]}`}
      >
        {member.role}
      </span>

      <select
        value={member.role}
        onChange={(e) => onRoleChange(e.target.value as Role)}
        disabled={rolePending}
        className="shrink-0 rounded-md border border-slate-300 px-2.5 py-1 text-xs disabled:opacity-50"
      >
        {ROLES.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>

      <button
        type="button"
        onClick={onRemove}
        disabled={removePending}
        className="shrink-0 rounded-md p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
        aria-label="Xóa thành viên"
        title="Xóa thành viên"
      >
        <Trash2 size={14} />
      </button>
    </li>
  );
}


function Avatar({ name, src }: { name: string; src: string | null }) {
  if (src) {
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <img
        src={src}
        alt=""
        className="h-8 w-8 shrink-0 rounded-full bg-slate-200 object-cover"
      />
    );
  }
  // Fallback: initials chip.
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700">
      {initial}
    </div>
  );
}
