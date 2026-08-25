import {
  DndContext,
  KeyboardSensor,
  MeasuringStrategy,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  tableFeatures,
  useTable,
  type SortingState,
} from '@tanstack/react-table'
import { useMemo, useState, type ReactNode } from 'react'

import EditableCell from './EditableCell'
import { ndpStatusClass } from '../ndp'
import type { BacklogRow, EditableField } from '../types'

interface ColumnSpec {
  id: keyof BacklogRow
  header: string
  wide?: boolean
  editField?: EditableField
  numeric?: boolean
}

const COLUMNS: ColumnSpec[] = [
  { id: 'rank', header: 'Rank', numeric: true, editField: 'rank' },
  { id: 'release', header: 'Release' },
  { id: 'release_title', header: 'Release Title', wide: true },
  { id: 'ndp', header: 'NDP' },
  { id: 'ndp_status', header: 'NDP Status' },
  { id: 'ndp_deploy_date', header: 'NDP Deploy Date' },
  { id: 'key', header: 'Backlog Key' },
  { id: 'summary', header: 'Summary', wide: true },
  { id: 'issue_type', header: 'Issue Type' },
  { id: 'status', header: 'Status' },
  { id: 'assignee', header: 'Assignee' },
  { id: 'developer', header: 'Developer', editField: 'developer' },
  { id: 'reporter', header: 'Reporter' },
  { id: 'priority', header: 'Priority' },
  { id: 'biz_domain', header: 'Biz Domain' },
  { id: 'req_qtr', header: 'Req Qtr' },
  { id: 'labels', header: 'Labels' },
  { id: 'backlog_source', header: 'Backlog Source' },
  { id: 'est_h', header: 'Est h', numeric: true },
  { id: 'spent_h', header: 'Spent h', numeric: true },
  { id: 'uat_eta', header: 'UAT ETA', editField: 'uat_eta' },
  { id: 'prod_eta', header: 'PROD ETA', editField: 'prod_eta' },
  { id: 'comments', header: 'Comments', wide: true, editField: 'comments' },
]

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, basic: sortFn_basic },
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString },
})

const helper = createColumnHelper<typeof features, BacklogRow>()

const columns = helper.columns(
  COLUMNS.map((col) =>
    helper.accessor((row: BacklogRow) => row[col.id], {
      id: col.id,
      header: col.header,
      sortFn: col.numeric ? 'basic' : 'alphanumeric',
    }),
  ),
)

const EMPTY: BacklogRow[] = []

interface Props {
  rows: BacklogRow[]
  editing: boolean
  dirty: Set<string>
  allowReorder: boolean
  globalFilter: string
  onGlobalFilterChange: (value: string) => void
  onEdit: (row: BacklogRow, field: EditableField, value: string) => void
  onReorder: (keys: string[]) => void
  onShowAudit: (row: BacklogRow) => void
  statusControl: ReactNode
  exportHref: string
  exportLabel: string
  exportAllHref: string
  exportAllLabel: string
}

function Row({
  row,
  editing,
  dragEnabled,
  dirty,
  onEdit,
  onShowAudit,
}: {
  row: BacklogRow
  editing: boolean
  dragEnabled: boolean
  dirty: Set<string>
  onEdit: Props['onEdit']
  onShowAudit: Props['onShowAudit']
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: row.key,
    disabled: !dragEnabled,
  })

  return (
    <tr
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={`${isDragging ? 'dragging' : ''} ${row.archived ? 'archived' : ''}`}
    >
      <td
        className={`drag${dragEnabled ? ' active' : ''}`}
        title={
          editing
            ? dragEnabled
              ? 'Drag to reorder, or type a number in Rank'
              : 'Clear the sort and filter to reorder'
            : 'Click Edit to reorder'
        }
        {...attributes}
        {...listeners}
      >
        {dragEnabled ? '\u22ee\u22ee' : ''}
      </td>
      {COLUMNS.map((col) => {
        const value = row[col.id]
        if (col.editField) {
          return (
            <EditableCell
              key={col.id}
              value={String(value ?? '')}
              editing={editing}
              changed={dirty.has(`${row.sheet}:${row.key}:${col.editField}`)}
              numeric={col.numeric}
              onCommit={(next) => onEdit(row, col.editField!, next)}
            />
          )
        }
        if (col.id === 'ndp_status') {
          return (
            <td key={col.id} className={ndpStatusClass(String(value))}>
              {String(value ?? '')}
            </td>
          )
        }
        if (col.id === 'key') {
          return (
            <td key={col.id}>
              <a
                href="#"
                onClick={(e) => {
                  e.preventDefault()
                  onShowAudit(row)
                }}
              >
                {row.key}
              </a>
              {row.archived && <span className="badge stale"> stale</span>}
            </td>
          )
        }
        return (
          <td key={col.id} className={col.wide ? 'wide' : undefined} title={String(value ?? '')}>
            {String(value ?? '')}
          </td>
        )
      })}
    </tr>
  )
}

export default function BacklogTable({
  rows,
  editing,
  dirty,
  allowReorder,
  globalFilter,
  onGlobalFilterChange,
  onEdit,
  onReorder,
  onShowAudit,
  statusControl,
  exportHref,
  exportLabel,
  exportAllHref,
  exportAllLabel,
}: Props) {
  const [sorting, setSorting] = useState<SortingState>([])

  const table = useTable({
    features,
    columns,
    data: rows.length ? rows : EMPTY,
    getRowId: (r: BacklogRow) => r.key,
    globalFilterFn: 'includesString',
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange,
  })

  const visibleRows = useMemo(
    () => table.getRowModel().rows.map((r) => r.original),
    [table, sorting, globalFilter, rows],
  )

  // Reordering only makes sense while every row is visible in its stored order.
  const canDrag = editing && allowReorder && sorting.length === 0 && globalFilter.trim() === ''

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const keys = visibleRows.map((r) => r.key)
    const from = keys.indexOf(String(active.id))
    const to = keys.indexOf(String(over.id))
    if (from < 0 || to < 0) return
    onReorder(arrayMove(keys, from, to))
  }

  return (
    <>
      <div className="table-status">
        {statusControl}
        {sorting.length > 0 && (
          <button onClick={() => setSorting([])}>
            Clear sort{editing ? ' (enables reorder)' : ''}
          </button>
        )}
        {editing && !canDrag && (
          <span className="muted">
            Reordering is off while the table is sorted or filtered by search or status
          </span>
        )}
        {/* All tabs is the default, because a workbook missing half its region
            sheets is the wrong thing to share or to feed back in. */}
        <a className="button export primary-link" href={exportAllHref} title={exportAllLabel}>
          Export to Excel (all tabs)
        </a>
        <a className="button" href={exportHref} title={exportLabel}>
          This tab only
        </a>
      </div>

      <div className="table-wrap">
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          modifiers={[restrictToVerticalAxis]}
          // Rows vary in height and the container scrolls, so cached rectangles from
          // drag start put the drop in the wrong place. Re-measure as rows shift.
          measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
          autoScroll={{ threshold: { x: 0, y: 0.2 } }}
          onDragEnd={handleDragEnd}
        >
          <table className="grid">
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id}>
                  <th style={{ width: 34 }} />
                  {group.headers.map((header) => (
                    <th key={header.id} onClick={header.column.getToggleSortingHandler()}>
                      {String(header.column.columnDef.header)}
                      <span className="sort">
                        {{ asc: '\u25b2', desc: '\u25bc' }[
                          header.column.getIsSorted() as 'asc' | 'desc'
                        ] ?? ''}
                      </span>
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              <SortableContext
                items={visibleRows.map((r) => r.key)}
                strategy={verticalListSortingStrategy}
              >
                {visibleRows.map((row) => (
                  <Row
                    key={row.key}
                    row={row}
                    editing={editing}
                    dragEnabled={canDrag}
                    dirty={dirty}
                    onEdit={onEdit}
                    onShowAudit={onShowAudit}
                  />
                ))}
              </SortableContext>
            </tbody>
          </table>
        </DndContext>
      </div>
    </>
  )
}
