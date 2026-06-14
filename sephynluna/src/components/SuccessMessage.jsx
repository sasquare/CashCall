function SuccessMessage({ orderData, orderId, onNewOrder }) {
  const isDemoOrder = orderId.startsWith('demo')
  const orderRef = isDemoOrder
    ? '#DEMO-MODE'
    : `#${orderId.substring(0, 8).toUpperCase()}`

  return (
    <div className="text-center py-4">

      {/* Gold checkmark circle */}
      <div
        className="w-20 h-20 mx-auto mb-6 rounded-full flex items-center justify-center"
        style={{ background: 'linear-gradient(135deg, #D4AF37, #F0D060)', boxShadow: '0 8px 30px rgba(212,175,55,0.35)' }}
      >
        <svg className="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      {/* Heading */}
      <h2
        className="text-3xl font-bold text-brand-purple mb-2"
        style={{ fontFamily: '"Cormorant Garamond", Georgia, serif' }}
      >
        Order Received!
      </h2>

      <p className="text-gray-500 text-sm mb-5 leading-relaxed max-w-sm mx-auto">
        Thank you, <span className="font-semibold text-brand-purple">{orderData.fullName}</span>!
        Your bespoke fragrance order is confirmed. We'll reach out to you at{' '}
        <span className="font-medium text-brand-purple break-all">{orderData.contactInfo}</span> soon.
      </p>

      {/* Order Reference */}
      <div
        className="rounded-xl p-4 mb-6"
        style={{ background: 'linear-gradient(135deg, #1E0437, #3B0764)' }}
      >
        <p className="text-purple-300 text-xs uppercase tracking-[0.2em] mb-2">Your Order Reference</p>
        <p className="text-brand-gold text-3xl font-bold tracking-widest" style={{ fontFamily: 'monospace' }}>
          {orderRef}
        </p>
        <p className="text-purple-300 text-xs mt-2">Screenshot this number for your records</p>
      </div>

      {/* Order summary */}
      <div className="rounded-xl border border-purple-100 bg-purple-50 p-5 mb-6 text-left">
        <p className="text-xs font-bold text-brand-purple tracking-[0.2em] uppercase mb-4 text-center">
          ✦ Order Summary ✦
        </p>

        <div className="space-y-3">
          <SummaryRow label="Perfume Type" value={orderData.perfumeType} />
          <SummaryRow label="Base" value={orderData.baseType} />
          <SummaryRow label="Quantity" value={orderData.quantity} />
          <SummaryRow label="Scent Notes" value={orderData.scentNotes} multiLine />
          {orderData.additionalInstructions && (
            <SummaryRow label="Instructions" value={orderData.additionalInstructions} multiLine />
          )}
        </div>
      </div>

      {/* Decorative divider */}
      <div className="flex items-center gap-3 mb-6">
        <div className="flex-1 h-px bg-purple-100" />
        <span className="text-brand-gold text-lg">✦</span>
        <div className="flex-1 h-px bg-purple-100" />
      </div>

      {/* New order button */}
      <button
        onClick={onNewOrder}
        className="w-full py-3.5 rounded-xl border-2 border-brand-purple text-brand-purple font-bold text-sm tracking-widest uppercase hover:bg-brand-purple hover:text-white transition-all duration-300 cursor-pointer"
      >
        Place Another Order
      </button>

      {isDemoOrder ? (
        <p className="text-xs text-amber-600 mt-4 bg-amber-50 rounded-lg p-3">
          🔧 This was a <strong>demo submission</strong> — nothing was saved.
          Add your Firebase credentials to go live.
        </p>
      ) : (
        <p className="text-xs text-gray-400 mt-4">
          Quote your order reference when contacting us on WhatsApp.
        </p>
      )}
    </div>
  )
}

function SummaryRow({ label, value, multiLine }) {
  return (
    <div className={`flex ${multiLine ? 'flex-col gap-0.5' : 'items-center justify-between'}`}>
      <span className="text-xs font-semibold text-purple-400 uppercase tracking-wide">{label}</span>
      <span className={`text-sm text-gray-700 ${multiLine ? '' : 'text-right font-medium'}`}>{value}</span>
    </div>
  )
}

export default SuccessMessage
