"use client";
import { FirmProfileForm } from "@aec/ui/bidradar";
import { useFirmProfile, useUpsertFirmProfile } from "@/hooks/bidradar";

export default function FirmProfilePage() {
  const { data, isLoading } = useFirmProfile();
  const upsert = useUpsertFirmProfile();

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Firm profile</h2>
        <p className="text-sm text-slate-500">
          BidRadar uses these signals to match and score tenders for your team.
        </p>
      </div>

      {isLoading ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
          Loading profile…
        </div>
      ) : (
        <FirmProfileForm
          profile={data ?? null}
          submitting={upsert.isPending}
          onSubmit={(input) => upsert.mutate(input)}
        />
      )}

      {upsert.isSuccess ? (
        <p className="text-sm text-emerald-700">Profile saved.</p>
      ) : null}
      {upsert.isError ? (
        <p className="text-sm text-rose-700">Failed to save. Please try again.</p>
      ) : null}
    </div>
  );
}
