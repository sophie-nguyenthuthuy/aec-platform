import { redirect } from "next/navigation";

export default function PulseProjectIndex({
  params,
}: {
  params: { project_id: string };
}) {
  redirect(`/pulse/${params.project_id}/dashboard`);
}
