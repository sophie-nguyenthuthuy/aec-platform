"use client";
import { useParams } from "next/navigation";
import type { MeetingStructured } from "@aec/types/pulse";
import { MeetingEditor } from "@aec/ui/pulse";
import { useStructureMeetingNotes } from "../../../../../hooks/pulse/useMeetings";
import { useCreateTask } from "../../../../../hooks/pulse/useTasks";

export default function PulseMeetingsPage() {
  const params = useParams<{ project_id: string }>();
  const projectId = params.project_id;

  const structure = useStructureMeetingNotes();
  const createTask = useCreateTask();

  async function onStructure(notes: string): Promise<MeetingStructured> {
    const note = await structure.mutateAsync({
      raw_notes: notes,
      project_id: projectId,
      persist: true,
    });
    if (!note.ai_structured) {
      throw new Error("Structuring returned no data");
    }
    return note.ai_structured;
  }

  function onCreateTask(title: string, deadline: string | null) {
    createTask.mutate({
      project_id: projectId,
      title,
      due_date: deadline ?? undefined,
    });
  }

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Meeting notes</h2>
      <MeetingEditor
        onStructure={onStructure}
        onCreateTask={onCreateTask}
      />
    </div>
  );
}
