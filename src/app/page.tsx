"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, Play } from "lucide-react";
import { HeroBackground } from "@/components/ui/hero-background";

export default function Home() {
  const [url, setUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  const validateUrl = (inputUrl: string) => {
    try {
      const urlObj = new URL(inputUrl.startsWith('http') ? inputUrl : `https://${inputUrl}`);
      return urlObj.protocol === 'http:' || urlObj.protocol === 'https:';
    } catch {
      return false;
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!url.trim()) {
      setError("Please enter a URL");
      return;
    }

    if (!validateUrl(url)) {
      setError("Please enter a valid URL (e.g., https://example.com)");
      return;
    }

    setIsSubmitting(true);
    
    try {
      const formattedUrl = url.startsWith('http') ? url : `https://${url}`;
      
      const response = await fetch('/api/analyze-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: formattedUrl }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.details || 'Failed to analyze URL.');
      }

      const analysis = await response.json();

      sessionStorage.setItem('targetUrl', formattedUrl);
      sessionStorage.setItem('pageAnalysis', JSON.stringify(analysis));
      
      router.push('/scenarios');
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process URL. Please try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <>
      <HeroBackground />
      <div className="container mx-auto px-4 py-16 flex flex-col items-center justify-center text-center min-h-[80vh]">
        {/* New Hero Section */}
        <h1 className="text-5xl md:text-7xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-slate-100 to-slate-400 pb-4">
          AI Test Runner
        </h1>
        <p className="text-lg md:text-xl text-slate-400 mb-12 max-w-3xl mx-auto">
          Transform web testing with AI-powered automation. Enter a URL to instantly generate and run comprehensive test scenarios.
        </p>

        {/* Main Form in a Frosted Card */}
        <div className="w-full max-w-2xl">
          <Card>
            <CardContent className="p-6">
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="flex flex-col sm:flex-row gap-2">
                  <Input
                    id="url"
                    type="text"
                    placeholder="Enter a website URL to begin..."
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    className="flex-1 text-base py-6 bg-transparent" // Adjusted for new design
                  />
                  <Button type="submit" disabled={isSubmitting} size="lg" className="flex items-center gap-2 text-base">
                    {isSubmitting ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : (
                      <Play className="w-5 h-5" />
                    )}
                    Analyze
                  </Button>
                </div>
                {error && (
                  <Alert variant="destructive" className="bg-red-500/10 border-red-500/30 text-red-400">
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}