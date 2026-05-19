import { NextResponse } from "next/server";
import getPool from "@/lib/db";

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    // Try to get a client from the pool and make a simple query
    const pool = getPool();
    await pool.query('SELECT 1');

    return NextResponse.json({
      status: "ok",
      message: "Service healthy"
    });
  } catch (error) {
    console.error("Health check failed:", error);
    // Do not expose internal error details
    return NextResponse.json({
      status: "error",
      message: "Service unavailable"
    }, { status: 503 });
  }
}