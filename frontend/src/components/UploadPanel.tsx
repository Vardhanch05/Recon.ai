import React, { useState, useRef } from 'react';
import { Upload, FileText, Sparkles, Check, AlertCircle, Settings } from 'lucide-react';

interface UploadPanelProps {
  onUpload: (settlementFile: File, ledgerFile: File, tolerance: number) => Promise<void>;
  isLoading: boolean;
}

export const UploadPanel: React.FC<UploadPanelProps> = ({ onUpload, isLoading }) => {
  const [settlementFile, setSettlementFile] = useState<File | null>(null);
  const [ledgerFile, setLedgerFile] = useState<File | null>(null);
  const [tolerance, setTolerance] = useState<number>(2);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const settlementInputRef = useRef<HTMLInputElement>(null);
  const ledgerInputRef = useRef<HTMLInputElement>(null);

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!settlementFile || !ledgerFile) {
      setErrorMsg('Please select both the Settlement CSV and Order Ledger CSV files.');
      return;
    }
    setErrorMsg(null);
    try {
      await onUpload(settlementFile, ledgerFile, tolerance);
    } catch (err: any) {
      setErrorMsg(err.message || 'Upload failed');
    }
  };

  // Quick-load demo files by creating File objects from the built-in synthetic datasets
  const loadDemoDataset = async () => {
    try {
      setErrorMsg(null);
      // Fetch synthetic batch from public/backend or embedded generator
      const settleSample = `gateway_txn_id,order_id,settled_amount,settlement_timestamp,fee_deducted,currency
pay_det_001,ORD_1001,980.00,2026-09-01T09:05:00Z,20.00,INR
pay_det_002,ORD_1002,1470.00,2026-09-01T09:10:00Z,30.00,INR
pay_det_003,ORD_1003,490.00,2026-09-01T09:15:00Z,10.00,INR
pay_det_004,ORD_1004,2450.00,2026-09-01T09:20:00Z,50.00,INR
pay_det_005,ORD_1005,980.00,2026-09-01T09:25:00Z,20.00,INR
pay_det_006,ORD_1006,4900.00,2026-09-01T09:30:00Z,100.00,INR
pay_det_007,ORD_1007,1470.00,2026-09-01T09:35:00Z,30.00,INR
pay_det_008,ORD_1008,980.00,2026-09-01T09:40:00Z,20.00,INR
pay_det_009,ORD_1009,2450.00,2026-09-01T09:45:00Z,50.00,INR
pay_det_010,ORD_1010,490.00,2026-09-01T09:50:00Z,10.00,INR
pay_det_011,ORD_1011,980.00,2026-09-01T09:55:00Z,20.00,INR
pay_det_012,ORD_1012,1470.00,2026-09-01T10:00:00Z,30.00,INR
pay_det_013,ORD_1013,2450.00,2026-09-01T10:05:00Z,50.00,INR
pay_det_014,ORD_1014,980.00,2026-09-01T10:10:00Z,20.00,INR
pay_det_015,ORD_1015,4900.00,2026-09-01T10:15:00Z,100.00,INR
pay_det_016,ORD_1016,490.00,2026-09-01T10:20:00Z,10.00,INR
pay_det_017,ORD_1017,980.00,2026-09-01T10:25:00Z,20.00,INR
pay_det_018,ORD_1018,1470.00,2026-09-01T10:30:00Z,30.00,INR
pay_det_019,ORD_1019,2450.00,2026-09-01T10:35:00Z,50.00,INR
pay_det_020,ORD_1020,980.00,2026-09-01T10:40:00Z,20.00,INR
pay_det_021,ORD_1021,490.00,2026-09-01T10:45:00Z,10.00,INR
pay_det_022,ORD_1022,1470.00,2026-09-01T10:50:00Z,30.00,INR
pay_det_023,ORD_1023,2450.00,2026-09-01T10:55:00Z,50.00,INR
pay_det_024,ORD_1024,4900.00,2026-09-01T11:00:00Z,100.00,INR
pay_det_025,ORD_1025,980.00,2026-09-01T11:05:00Z,20.00,INR
pay_det_026,ORD_1026,1470.00,2026-09-01T11:10:00Z,30.00,INR
pay_det_027,ORD_1027,490.00,2026-09-01T11:15:00Z,10.00,INR
pay_det_028,ORD_1028,2450.00,2026-09-01T11:20:00Z,50.00,INR
pay_det_029,ORD_1029,980.00,2026-09-01T11:25:00Z,20.00,INR
pay_det_030,ORD_1030,1470.00,2026-09-01T11:30:00Z,30.00,INR
pay_det_031,ORD_1031,490.00,2026-09-01T11:35:00Z,10.00,INR
pay_det_032,ORD_1032,2450.00,2026-09-01T11:40:00Z,50.00,INR
pay_det_033,ORD_1033,980.00,2026-09-01T11:45:00Z,20.00,INR
pay_det_034,ORD_1034,4900.00,2026-09-01T11:50:00Z,100.00,INR
pay_det_035,ORD_1035,1470.00,2026-09-01T11:55:00Z,30.00,INR
pay_det_036,ORD_1036,490.00,2026-09-01T12:00:00Z,10.00,INR
pay_det_037,ORD_1037,980.00,2026-09-01T12:05:00Z,20.00,INR
pay_det_038,ORD_1038,2450.00,2026-09-01T12:10:00Z,50.00,INR
pay_det_039,ORD_1039,1470.00,2026-09-01T12:15:00Z,30.00,INR
pay_det_040,ORD_1040,4900.00,2026-09-01T12:20:00Z,100.00,INR
pay_det_041,,980.00,2026-09-01T12:25:00Z,20.00,INR
pay_det_042,,1470.00,2026-09-01T12:30:00Z,30.00,INR
pay_det_043,,490.00,2026-09-01T12:35:00Z,10.00,INR
pay_det_044,,2450.00,2026-09-01T12:40:00Z,50.00,INR
pay_exp_001,ORD_1045,976.40,2026-09-01T14:05:00Z,20.00,INR
pay_exp_002,ORD_1046,1929.20,2026-09-01T14:10:00Z,40.00,INR
pay_exp_003,ORD_1047,1460.00,2026-09-01T14:15:00Z,30.00,INR
pay_exp_004,ORD_1048,780.00,2026-09-01T14:20:00Z,20.00,INR
pay_exp_005,ORD_1049,2895.00,2026-09-01T14:25:00Z,60.00,INR
pay_exp_006,ORD_1050,1021.68,2026-09-01T14:30:00Z,24.00,INR
pay_exp_007,ORD_1051,2301.50,2026-09-01T14:35:00Z,50.00,INR
pay_exp_008,ORD_1052,964.40,2026-09-01T14:40:00Z,20.00,INR
pay_unres_001,ORD_1053,1650.00,2026-09-01T17:05:00Z,40.00,INR
pay_unres_002,ORD_1054,4200.00,2026-09-01T17:10:00Z,100.00,INR
pay_unres_003,ORD_1055,980.00,2026-09-01T17:15:00Z,30.00,INR`;

      const ledgerSample = `order_id,billed_amount,order_timestamp,refund_amount,is_international,payment_method
ORD_1001,1000.00,2026-09-01T09:05:00Z,0.0,False,card
ORD_1002,1500.00,2026-09-01T09:10:00Z,0.0,False,upi
ORD_1003,500.00,2026-09-01T09:15:00Z,0.0,False,netbanking
ORD_1004,2500.00,2026-09-01T09:20:00Z,0.0,False,card
ORD_1005,1000.00,2026-09-01T09:25:00Z,0.0,False,upi
ORD_1006,5000.00,2026-09-01T09:30:00Z,0.0,False,card
ORD_1007,1500.00,2026-09-01T09:35:00Z,0.0,False,netbanking
ORD_1008,1000.00,2026-09-01T09:40:00Z,0.0,False,card
ORD_1009,2500.00,2026-09-01T09:45:00Z,0.0,False,upi
ORD_1010,500.00,2026-09-01T09:50:00Z,0.0,False,card
ORD_1011,1000.00,2026-09-01T09:55:00Z,0.0,False,netbanking
ORD_1012,1500.00,2026-09-01T10:00:00Z,0.0,False,card
ORD_1013,2500.00,2026-09-01T10:05:00Z,0.0,False,upi
ORD_1014,1000.00,2026-09-01T10:10:00Z,0.0,False,card
ORD_1015,5000.00,2026-09-01T10:15:00Z,0.0,False,netbanking
ORD_1016,500.00,2026-09-01T10:20:00Z,0.0,False,card
ORD_1017,1000.00,2026-09-01T10:25:00Z,0.0,False,upi
ORD_1018,1500.00,2026-09-01T10:30:00Z,0.0,False,card
ORD_1019,2500.00,2026-09-01T10:35:00Z,0.0,False,netbanking
ORD_1020,1000.00,2026-09-01T10:40:00Z,0.0,False,card
ORD_1021,500.00,2026-09-01T10:45:00Z,0.0,False,upi
ORD_1022,1500.00,2026-09-01T10:50:00Z,0.0,False,card
ORD_1023,2500.00,2026-09-01T10:55:00Z,0.0,False,netbanking
ORD_1024,5000.00,2026-09-01T11:00:00Z,0.0,False,card
ORD_1025,1000.00,2026-09-01T11:05:00Z,0.0,False,upi
ORD_1026,1500.00,2026-09-01T11:10:00Z,0.0,False,card
ORD_1027,500.00,2026-09-01T11:15:00Z,0.0,False,netbanking
ORD_1028,2500.00,2026-09-01T11:20:00Z,0.0,False,card
ORD_1029,1000.00,2026-09-01T11:25:00Z,0.0,False,upi
ORD_1030,1500.00,2026-09-01T11:30:00Z,0.0,False,card
ORD_1031,500.00,2026-09-01T11:35:00Z,0.0,False,netbanking
ORD_1032,2500.00,2026-09-01T11:40:00Z,0.0,False,card
ORD_1033,1000.00,2026-09-01T11:45:00Z,0.0,False,upi
ORD_1034,5000.00,2026-09-01T11:50:00Z,0.0,False,card
ORD_1035,1500.00,2026-09-01T11:55:00Z,0.0,False,netbanking
ORD_1036,500.00,2026-09-01T12:00:00Z,0.0,False,card
ORD_1037,1000.00,2026-09-01T12:05:00Z,0.0,False,upi
ORD_1038,2500.00,2026-09-01T12:10:00Z,0.0,False,card
ORD_1039,1500.00,2026-09-01T12:15:00Z,0.0,False,netbanking
ORD_1040,5000.00,2026-09-01T12:20:00Z,0.0,False,card
ORD_1041,1000.00,2026-09-01T12:25:00Z,0.0,False,upi
ORD_1042,1500.00,2026-09-01T12:30:00Z,0.0,False,card
ORD_1043,500.00,2026-09-01T12:35:00Z,0.0,False,netbanking
ORD_1044,2500.00,2026-09-01T12:40:00Z,0.0,False,card
ORD_1045,1000.00,2026-09-01T14:05:00Z,0.0,False,card
ORD_1046,2000.00,2026-09-01T14:10:00Z,0.0,True,card
ORD_1047,1500.00,2026-09-01T14:15:00Z,0.0,False,card
ORD_1048,1000.00,2026-09-01T14:20:00Z,200.0,False,card
ORD_1049,3000.00,2026-09-01T14:25:00Z,0.0,True,card
ORD_1050,1200.00,2026-09-01T14:30:00Z,150.0,False,card
ORD_1051,2500.00,2026-09-01T14:35:00Z,100.0,True,card
ORD_1052,1000.00,2026-09-01T14:40:00Z,0.0,True,card
ORD_1053,2000.00,2026-09-01T17:05:00Z,0.0,False,card
ORD_1054,5000.00,2026-09-01T17:10:00Z,0.0,False,card
ORD_1055,1500.00,2026-09-01T17:15:00Z,0.0,False,card`;

      const sFile = new File([settleSample], 'settlement_synthetic.csv', { type: 'text/csv' });
      const lFile = new File([ledgerSample], 'ledger_synthetic.csv', { type: 'text/csv' });

      setSettlementFile(sFile);
      setLedgerFile(lFile);
      await onUpload(sFile, lFile, tolerance);
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to auto-load demo dataset');
    }
  };

  return (
    <div className="glass-card" style={{ padding: '28px', marginBottom: '32px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Upload size={20} color="var(--accent-blue)" />
            Ingest Settlement & Order Ledger
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            Upload your Razorpay settlement export and internal merchant ledger to initiate automated reconciliation.
          </p>
        </div>

        {/* Demo Preset Button */}
        <button
          type="button"
          onClick={loadDemoDataset}
          disabled={isLoading}
          className="btn"
          style={{
            background: 'linear-gradient(135deg, rgba(51, 149, 255, 0.15) 0%, rgba(139, 92, 246, 0.15) 100%)',
            border: '1px solid rgba(51, 149, 255, 0.4)',
            color: '#60a5fa'
          }}
        >
          <Sparkles size={16} />
          <span>Load 55-Record Demo Dataset</span>
        </button>
      </div>

      {errorMsg && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '12px 16px',
          background: 'rgba(239, 68, 68, 0.12)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: 'var(--radius-md)',
          color: '#f87171',
          fontSize: '13px',
          marginBottom: '20px'
        }}>
          <AlertCircle size={16} />
          <span>{errorMsg}</span>
        </div>
      )}

      <form onSubmit={handleUploadSubmit}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', marginBottom: '24px' }}>
          
          {/* Dropzone 1: Settlement CSV */}
          <div
            onClick={() => settlementInputRef.current?.click()}
            style={{
              border: `2px dashed ${settlementFile ? 'var(--accent-green)' : 'var(--border-strong)'}`,
              borderRadius: 'var(--radius-lg)',
              padding: '24px',
              textAlign: 'center',
              cursor: 'pointer',
              background: settlementFile ? 'rgba(16, 185, 129, 0.05)' : 'var(--bg-inset)',
              transition: 'all 0.2s ease'
            }}
          >
            <input
              type="file"
              ref={settlementInputRef}
              accept=".csv"
              style={{ display: 'none' }}
              onChange={(e) => setSettlementFile(e.target.files?.[0] || null)}
            />
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '50%',
              background: settlementFile ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-card-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 12px auto',
              color: settlementFile ? 'var(--accent-green)' : 'var(--text-secondary)'
            }}>
              {settlementFile ? <Check size={22} /> : <FileText size={22} />}
            </div>
            <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
              {settlementFile ? settlementFile.name : 'Settlement File (CSV)'}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
              {settlementFile ? `${(settlementFile.size / 1024).toFixed(1)} KB` : 'Click to browse or drop settlement file'}
            </div>
          </div>

          {/* Dropzone 2: Order Ledger CSV */}
          <div
            onClick={() => ledgerInputRef.current?.click()}
            style={{
              border: `2px dashed ${ledgerFile ? 'var(--accent-green)' : 'var(--border-strong)'}`,
              borderRadius: 'var(--radius-lg)',
              padding: '24px',
              textAlign: 'center',
              cursor: 'pointer',
              background: ledgerFile ? 'rgba(16, 185, 129, 0.05)' : 'var(--bg-inset)',
              transition: 'all 0.2s ease'
            }}
          >
            <input
              type="file"
              ref={ledgerInputRef}
              accept=".csv"
              style={{ display: 'none' }}
              onChange={(e) => setLedgerFile(e.target.files?.[0] || null)}
            />
            <div style={{
              width: '44px',
              height: '44px',
              borderRadius: '50%',
              background: ledgerFile ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-card-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 12px auto',
              color: ledgerFile ? 'var(--accent-green)' : 'var(--text-secondary)'
            }}>
              {ledgerFile ? <Check size={22} /> : <FileText size={22} />}
            </div>
            <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>
              {ledgerFile ? ledgerFile.name : 'Merchant Order Ledger (CSV)'}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
              {ledgerFile ? `${(ledgerFile.size / 1024).toFixed(1)} KB` : 'Click to browse or drop ledger file'}
            </div>
          </div>

        </div>

        {/* Tolerance config & Action button */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Settings size={16} color="var(--text-muted)" />
            <label style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              Fallback Timestamp Window:
            </label>
            <input
              type="number"
              min="0"
              max="60"
              value={tolerance}
              onChange={(e) => setTolerance(parseInt(e.target.value) || 2)}
              style={{
                width: '64px',
                padding: '6px 10px',
                background: 'var(--bg-inset)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                textAlign: 'center'
              }}
            />
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>seconds</span>
          </div>

          <button
            type="submit"
            disabled={!settlementFile || !ledgerFile || isLoading}
            className="btn btn-primary"
            style={{ padding: '12px 28px', fontSize: '14px' }}
          >
            <Upload size={16} />
            <span>{isLoading ? 'Processing Files...' : 'Upload & Start Pipeline'}</span>
          </button>
        </div>
      </form>
    </div>
  );
};
