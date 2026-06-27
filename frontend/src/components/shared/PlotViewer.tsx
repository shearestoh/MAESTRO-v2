import { useState, useEffect } from "react";
import { useMaestroStore }     from "@/store/maestroStore";
import { api }                 from "@/lib/api";
import { Loader2, ImageOff }   from "lucide-react";

export function PlotViewer() {
  const sessionId       = useMaestroStore((s) => s.sessionId);
  const showPlotterImage= useMaestroStore((s) => s.state?.show_plotter_image);
  const bgJobStatus     = useMaestroStore((s) => s.state?.background_job_status);

  const [imgSrc,  setImgSrc]  = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(false);

  useEffect(() => {
    // Only attempt to load when backend signals plot is ready
    if (!sessionId || !showPlotterImage) {
      setImgSrc(null);
      return;
    }

    setLoading(true);
    setError(false);

    // Add cache-buster so browser doesn't serve stale image
    const url = `${api.getPlotUrl(sessionId)}?t=${Date.now()}`;

    // Pre-load the image to detect errors before rendering
    const img = new Image();
    img.onload = () => {
      setImgSrc(url);
      setLoading(false);
    };
    img.onerror = () => {
      setError(true);
      setLoading(false);
    };
    img.src = url;
  }, [sessionId, showPlotterImage, bgJobStatus]);

  // Nothing to show
  if (!showPlotterImage && !loading) return null;

  return (
    <div className="glass-panel p-4 space-y-3">
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-2">
        📊 Summary Figure
      </div>

      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 size={20} className="text-blue-400 animate-spin" />
          <span className="ml-2 text-xs text-slate-500">Loading plot...</span>
        </div>
      )}

      {error && (
        <div className="flex items-center justify-center py-8 gap-2 text-slate-500">
          <ImageOff size={16} />
          <span className="text-xs">Plot not available yet</span>
        </div>
      )}

      {imgSrc && !loading && !error && (
        <div className="rounded-lg overflow-hidden border border-slate-700">
          <img
            src={imgSrc}
            alt="Optimisation summary figure"
            className="w-full h-auto"
          />
        </div>
      )}

      {imgSrc && (
        <a
          href={imgSrc}
          download="maestro_summary_plot.png"
          className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          ⬇ Download PNG
        </a>
      )}
    </div>
  );
}