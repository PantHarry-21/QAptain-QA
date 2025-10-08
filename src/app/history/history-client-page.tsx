'use client';

import * as React from 'react';
import { useQuery } from '@tanstack/react-query';
import { useRouter, usePathname, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { format } from 'date-fns';
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
  SortingState,
  getSortedRowModel,
} from '@tanstack/react-table';

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

// Define the type for our test session data
interface TestSession {
  id: string;
  name: string | null;
  created_at: string;
  status: string;
  total_steps: number;
  passed_steps: number;
  failed_steps: number;
}

// Fetcher function for react-query
async function fetchHistory(query: string): Promise<any> {
  const res = await fetch(`/api/history?${query}`);
  if (!res.ok) {
    throw new Error('Failed to fetch test history');
  }
  return res.json();
}

export default function HistoryClientPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const page = searchParams.get('page') ?? '1';
  const limit = searchParams.get('limit') ?? '10';
  const search = searchParams.get('search') ?? '';
  const [sorting, setSorting] = React.useState<SortingState>([
    { id: 'created_at', desc: true },
  ]);

  const [debouncedSearch, setDebouncedSearch] = React.useState(search);

  // Debounce search input
  React.useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(search);
    }, 500);
    return () => clearTimeout(handler);
  }, [search]);

  const createQueryString = React.useCallback(
    (params: Record<string, string | number | null>) => {
      const newSearchParams = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(params)) {
        if (value === null) {
          newSearchParams.delete(key);
        } else {
          newSearchParams.set(key, String(value));
        }
      }
      return newSearchParams.toString();
    },
    [searchParams]
  );

  const queryKey = ['history', page, limit, debouncedSearch, sorting];
  const queryString = createQueryString({
    page,
    limit,
    search: debouncedSearch,
    sortBy: sorting[0]?.id,
    order: sorting[0]?.desc ? 'desc' : 'asc',
  });

  const { data, isLoading, isError } = useQuery({
    queryKey,
    queryFn: () => fetchHistory(queryString),
  });

  const columns: ColumnDef<TestSession>[] = React.useMemo(
    () => [
      {
        accessorKey: 'name',
        header: 'Test Name',
        cell: ({ row }) => (
          <Link href={`/results/${row.original.id}`}>
            <span className="font-medium text-blue-600 hover:underline">
              {row.original.name || `Test Run ${row.original.id.substring(0, 8)}`}
            </span>
          </Link>
        ),
      },
      {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => {
          const status = row.original.status.toLowerCase();
          let variant: 'default' | 'destructive' | 'outline' = 'default';
          if (status === 'completed' || status === 'passed') variant = 'default';
          else if (status === 'failed') variant = 'destructive';
          else variant = 'outline';
          return <Badge variant={variant}>{row.original.status}</Badge>;
        },
      },
      {
        accessorKey: 'created_at',
        header: 'Date',
        cell: ({ row }) => format(new Date(row.original.created_at), 'PPpp'),
      },
      {
        header: 'Progress',
        cell: ({ row }) => (
          <span>
            {row.original.passed_steps} / {row.original.total_steps} steps
          </span>
        ),
      },
      {
        accessorKey: 'failed_steps',
        header: 'Failed Steps',
      },
    ],
    []
  );

  const table = useReactTable({
    data: data?.data ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    manualPagination: true,
    manualSorting: true,
    pageCount: data?.pagination?.totalPages ?? -1,
    rowCount: data?.pagination?.total ?? 0,
    state: {
      sorting,
    },
    onSortingChange: setSorting,
  });

  return (
    <div className="container mx-auto py-10">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold">Test Run History</h1>
          <p className="text-muted-foreground">A list of all your previous test executions.</p>
        </div>
        <Input
          placeholder="Search by name or ID..."
          value={search}
          onChange={(e) => router.push(`${pathname}?${createQueryString({ search: e.target.value, page: '1' })}`)}
          className="max-w-sm"
        />
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead key={header.id} onClick={header.column.getToggleSortingHandler()}>
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {{
                      asc: ' 🔼',
                      desc: ' 🔽',
                    }[header.column.getIsSorted() as string] ?? null}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 10 }).map((_, i) => (
                <TableRow key={i}>
                  {columns.map((col, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-end space-x-2 py-4">
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push(`${pathname}?${createQueryString({ page: Math.max(1, parseInt(page) - 1) })}`)}
          disabled={parseInt(page) <= 1}
        >
          Previous
        </Button>
        <span className="text-sm">
          Page {page} of {data?.pagination?.totalPages ?? 1}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push(`${pathname}?${createQueryString({ page: parseInt(page) + 1 })}`)}
          disabled={parseInt(page) >= (data?.pagination?.totalPages ?? 1)}
        >
          Next
        </Button>
      </div>
    </div>
  );
}
