"use client";

import { useState } from "react";
import { Copy, Trash2, UserPlus } from "lucide-react";

import {
  Alert,
  Button,
  Input,
  PageHeader,
  Spinner,
} from "@aec/ui/primitives";
import {
  type Invitation,
  type InvitationCreated,
  type OrgMember,
  type Role,
  useInviteMember,
  useOrgMembers,
  usePendingInvitations,
  useRemoveMember,
  useRevokeInvitation,
  useUpdateMemberRole,
} from "@/hooks/org";


// Invitable roles match the api's _ASSIGNABLE_ROLES set — `owner` is
// excluded so an admin can't promote an invitee above themselves.
const ROLES: Array<{ value: Role; label: string; help: string }> = [
  { value: "viewer",  label: "Viewer",  help: "Read-only across modules" },
  { value: "member",  label: "Member",  help: "Read + write within modules" },
  { value: "admin",   label: "Admin",   help: "Full read/write + manage members" },
];

const ROLE_BADGE: Record<Role, string> = {
  owner:  "bg-rose-100 text-rose-800",
  admin:  "bg-indigo-100 text-indigo-800",
  member: "bg-blue-100 text-blue-800",
  viewer: "bg-muted text-muted-foreground",
};

export default function MembersPage() {
  const { data: members, isLoading, error } = useOrgMembers();
  const { data: invitations } = usePendingInvitations();
  const invite = useInviteMember();
  const revoke = useRevokeInvitation();
  const updateRole = useUpdateMemberRole();
  const removeMember = useRemoveMember();

  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("member");
  // Last successful invite — surface the accept URL so the admin can
  // copy it. Goes away once SMTP is wired and we mail the link directly.
  const [lastInvite, setLastInvite] = useState<InvitationCreated | null>(null);

  const handleInvite = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    invite.mutate(
      { email: inviteEmail.trim(), role: inviteRole },
      {
        onSuccess: (created) => {
          setLastInvite(created);
          setInviteEmail("");
          setInviteRole("member");
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Thành viên"
        description="Quản lý quyền truy cập của thành viên trong tổ chức."
      />

      {/* ---------------- Invite form (admin/owner only) ---------------- */}
      <section className="rounded-xl border bg-card p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded bg-indigo-100 text-indigo-700">
            <UserPlus size={14} />
          </span>
          <h3 className="text-sm font-semibold text-foreground">Mời thành viên</h3>
        </div>
        <form
          onSubmit={handleInvite}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="flex-1 min-w-[260px]">
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Email
            </label>
            <Input
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="newuser@example.com"
              className="mt-1"
            />
          </div>
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Vai trò
            </label>
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as Role)}
              className="mt-1 rounded-md border bg-background px-3 py-1.5 text-sm focus:border-primary focus:outline-none"
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="submit"
            disabled={!inviteEmail.trim()}
            loading={invite.isPending}
          >
            {invite.isPending ? "Đang mời..." : "Gửi lời mời"}
          </Button>
        </form>
        {invite.isError && (
          <Alert variant="destructive" className="mt-2">
            {(invite.error as Error)?.message ?? "Mời thất bại"}
          </Alert>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          Hệ thống tạo một liên kết một lần. Người được mời mở liên kết, đặt
          mật khẩu, và được thêm vào tổ chức tự động.
        </p>

        {lastInvite && (
          <AcceptUrlChip invitation={lastInvite} onDismiss={() => setLastInvite(null)} />
        )}
      </section>

      {/* ---------------- Pending invitations ---------------- */}
      {invitations && invitations.length > 0 && (
        <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-amber-800">
              Lời mời đang chờ ({invitations.length})
            </span>
          </div>
          <ul className="divide-y divide-amber-200">
            {invitations.map((inv) => (
              <PendingInvitationRow
                key={inv.id}
                invitation={inv}
                onRevoke={() => {
                  if (window.confirm(`Hủy lời mời cho ${inv.email}?`)) {
                    revoke.mutate(inv.id);
                  }
                }}
                pending={revoke.isPending && revoke.variables === inv.id}
              />
            ))}
          </ul>
        </section>
      )}

      {/* ---------------- Members list ---------------- */}
      <section className="rounded-xl border bg-card">
        <header className="border-b px-5 py-3">
          <h3 className="text-sm font-semibold text-foreground">
            Danh sách thành viên
          </h3>
        </header>

        {isLoading ? (
          <div className="px-5 py-8">
            <Spinner label="Đang tải" />
          </div>
        ) : error ? (
          <div className="px-5 py-8">
            <Alert variant="destructive">
              Không thể tải danh sách thành viên.
            </Alert>
          </div>
        ) : !members || members.length === 0 ? (
          <p className="px-5 py-8 text-sm text-muted-foreground">Chưa có thành viên nào.</p>
        ) : (
          <ul className="divide-y">
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
          <div className="border-t px-5 py-2">
            <Alert variant="destructive">
              {(updateRole.error as Error)?.message ??
                (removeMember.error as Error)?.message}
            </Alert>
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
          <p className="truncate text-sm font-medium text-foreground">
            {member.full_name ?? member.email}
          </p>
          {member.full_name && (
            <p className="truncate text-xs text-muted-foreground">{member.email}</p>
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
        className="shrink-0 rounded-md border bg-background px-2.5 py-1 text-xs disabled:opacity-50"
      >
        {ROLES.map((r) => (
          <option key={r.value} value={r.value}>
            {r.label}
          </option>
        ))}
      </select>

      <Button
        variant="ghost"
        size="icon"
        onClick={onRemove}
        disabled={removePending}
        aria-label="Xóa thành viên"
        title="Xóa thành viên"
        className="h-7 w-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
      >
        <Trash2 size={14} />
      </Button>
    </li>
  );
}


function AcceptUrlChip({
  invitation,
  onDismiss,
}: {
  invitation: InvitationCreated;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(invitation.accept_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Older browsers / non-secure contexts: fall through to visible URL.
    }
  }

  return (
    <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-emerald-900">
          Lời mời đã tạo cho <span className="font-mono">{invitation.email}</span>. Sao chép
          liên kết và gửi cho người được mời:
        </p>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-[11px] text-emerald-700 hover:text-emerald-900"
        >
          ×
        </button>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <code className="flex-1 truncate rounded bg-card px-2 py-1 text-xs text-foreground">
          {invitation.accept_url}
        </code>
        <button
          type="button"
          onClick={copy}
          className="inline-flex shrink-0 items-center gap-1 rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
        >
          <Copy size={12} />
          {copied ? "Đã sao chép" : "Sao chép"}
        </button>
      </div>
      <p className="mt-2 text-[11px] text-emerald-800">
        Hết hạn: {new Date(invitation.expires_at).toLocaleString("vi-VN")}
      </p>
    </div>
  );
}


function PendingInvitationRow({
  invitation,
  onRevoke,
  pending,
}: {
  invitation: Invitation;
  onRevoke: () => void;
  pending: boolean;
}) {
  return (
    <li className="flex items-center gap-4 py-2">
      <div className="flex-1 min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{invitation.email}</p>
        <p className="text-xs text-muted-foreground">
          Vai trò: {invitation.role} · Hết hạn{" "}
          {new Date(invitation.expires_at).toLocaleDateString("vi-VN")}
        </p>
      </div>
      <button
        type="button"
        onClick={onRevoke}
        disabled={pending}
        className="shrink-0 rounded-md px-2.5 py-1 text-xs text-amber-900 hover:bg-amber-100 disabled:opacity-50"
      >
        {pending ? "Đang hủy..." : "Hủy"}
      </button>
    </li>
  );
}


function Avatar({ name, src }: { name: string; src: string | null }) {
  if (src) {
    // Plain <img> is intentional here — avatar URLs come from arbitrary
    // upstream identity providers (Google, etc.), and `next/image` would
    // require enumerating every host in `next.config.mjs` or running them
    // through a Vercel image optimizer for a 32×32 thumbnail. Not worth it.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt=""
        className="h-8 w-8 shrink-0 rounded-full bg-muted object-cover"
      />
    );
  }
  // Fallback: initials chip.
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold text-foreground">
      {initial}
    </div>
  );
}
