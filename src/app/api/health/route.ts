import { NextResponse } from "next/server";
import pool from "@/lib/db";

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    // Try to get a client from the pool and make a simple query
    const client = await pool.connect();
    await client.query('SELECT 1');
    client.release(); // Release the client back to the pool

    return NextResponse.json({ 
      status: "ok", 
      message: "API is healthy and database connection is successful." 
    });
  } catch (error) {
    console.error("Health check failed:", error);
    const errorMessage = error instanceof Error ? error.message : "An unknown error occurred.";
    return NextResponse.json({ 
      status: "error", 
      message: "API is running, but the database connection failed.",
      error: errorMessage
    }, { status: 500 });
  }
}