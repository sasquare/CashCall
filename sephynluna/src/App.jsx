import { useState } from 'react'
import OrderForm from './components/OrderForm'
import SuccessMessage from './components/SuccessMessage'
import './App.css'

function App() {
  const [submission, setSubmission] = useState(null) // { orderData, orderId }

  const handleSuccess = (orderData, orderId) => {
    setSubmission({ orderData, orderId })
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleNewOrder = () => {
    setSubmission(null)
  }

  return (
    <div className="min-h-screen" style={{ background: 'linear-gradient(160deg, #1E0437 0%, #3B0764 50%, #4A0E8F 100%)' }}>

      {/* Header */}
      <header className="pt-10 pb-6 px-4 text-center">
        <div className="flex items-center justify-center gap-3 mb-4">
          <span className="text-brand-gold opacity-60 text-xl">─────</span>
          <span className="text-brand-gold text-2xl">✦</span>
          <span className="text-brand-gold opacity-60 text-xl">─────</span>
        </div>

        <h1
          className="text-white text-4xl md:text-6xl font-bold tracking-widest uppercase"
          style={{ fontFamily: '"Cormorant Garamond", Georgia, serif', letterSpacing: '0.15em' }}
        >
          SephynLuna
        </h1>

        <p
          className="text-brand-gold text-xl md:text-2xl italic mt-1"
          style={{ fontFamily: '"Cormorant Garamond", Georgia, serif' }}
        >
          Perfumery Hub
        </p>

        <div className="mt-3 text-purple-300 text-xs tracking-[0.25em] uppercase">
          Bespoke Fragrances for the Discerning Soul
        </div>

        <div className="flex items-center justify-center gap-3 mt-4">
          <span className="text-brand-gold opacity-60 text-xl">─────</span>
          <span className="text-brand-gold text-2xl">✦</span>
          <span className="text-brand-gold opacity-60 text-xl">─────</span>
        </div>
      </header>

      {/* Form Card */}
      <main className="px-4 pb-16">
        <div className="max-w-lg mx-auto">
          <div className="bg-white rounded-2xl shadow-2xl overflow-hidden">
            {/* Card accent bar */}
            <div className="h-1.5" style={{ background: 'linear-gradient(90deg, #3B0764, #D4AF37, #3B0764)' }} />

            <div className="p-6 md:p-10">
              {submission ? (
                <SuccessMessage
                  orderData={submission.orderData}
                  orderId={submission.orderId}
                  onNewOrder={handleNewOrder}
                />
              ) : (
                <>
                  <div className="text-center mb-8">
                    <h2
                      className="text-2xl font-bold text-brand-purple"
                      style={{ fontFamily: '"Cormorant Garamond", Georgia, serif' }}
                    >
                      Place Your Order
                    </h2>
                    <p className="text-gray-500 text-sm mt-1">
                      Fill in the details below and we'll craft your signature scent.
                    </p>
                  </div>
                  <OrderForm onSuccess={handleSuccess} />
                </>
              )}
            </div>
          </div>

          {/* Footer */}
          <p className="text-center text-purple-300 text-xs mt-6 tracking-wide">
            © SephynLuna Perfumery Hub &nbsp;·&nbsp; By Maria Adewolu Sasa
          </p>
        </div>
      </main>
    </div>
  )
}

export default App
