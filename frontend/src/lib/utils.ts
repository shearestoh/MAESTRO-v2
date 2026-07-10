import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Sample } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getBestOutput(sample: Sample, outputName: string): number | null {
  const values = sample.results
    .filter((r) => outputName in r.outputs)
    .map((r) => r.outputs[outputName]);
  return values.length > 0 ? Math.max(...values) : null;
}