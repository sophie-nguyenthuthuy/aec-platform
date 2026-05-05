"use client";

import { Search } from "lucide-react";
import { useState } from "react";

interface RegulationSearchProps {
  onSearch: (query: string) => void;
  placeholder?: string;
  defaultValue?: string;
  loading?: boolean;
}

export function RegulationSearch({
  onSearch,
  placeholder = "Tìm kiếm quy chuẩn, tiêu chuẩn...",
  defaultValue = "",
  loading = false,
}: RegulationSearchProps): JSX.Element {
  const [value, setValue] = useState(defaultValue);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSearch(value.trim());
      }}
      className="relative flex w-full items-center"
    >
      <Search
        size={18}
        className="pointer-events-none absolute left-3 text-slate-400"
      />
      <input
        type="search"
        aria-label="Tìm kiếm quy chuẩn"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-slate-300 bg-white py-2.5 pl-10 pr-24 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 placeholder:text-slate-500"
      />
      <button
        type="submit"
        disabled={loading}
        className="absolute right-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {loading ? "Đang tìm..." : "Tìm"}
      </button>
    </form>
  );
}
