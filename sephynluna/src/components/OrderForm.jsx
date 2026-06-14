import { useState } from 'react'
import { collection, addDoc, serverTimestamp } from 'firebase/firestore'
import emailjs from '@emailjs/browser'
import { db, isFirebaseReady } from '../firebase'

const INITIAL_FORM = {
  fullName: '',
  contactInfo: '',
  perfumeType: '',
  baseType: '',
  scentNotes: '',
  quantity: 1,
  additionalInstructions: '',
}

const inputBase =
  'w-full px-4 py-3 rounded-lg border text-gray-800 placeholder-gray-400 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-brand-purple transition-all duration-200 ' +
  'hover:border-purple-400'

const inputValid = 'border-purple-200 bg-white'
const inputError = 'border-red-400 bg-red-50 focus:ring-red-300'

function FieldError({ msg }) {
  if (!msg) return null
  return <p className="text-red-500 text-xs mt-1.5 flex items-center gap-1">⚠ {msg}</p>
}

function Label({ htmlFor, children, optional }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-semibold text-brand-purple mb-1.5">
      {children}
      {optional
        ? <span className="text-gray-400 font-normal ml-1">(optional)</span>
        : <span className="text-brand-gold ml-1">*</span>
      }
    </label>
  )
}

function RadioCard({ name, value, selected, onChange, label, description }) {
  return (
    <label
      className={
        'flex flex-col items-center justify-center gap-1 px-3 py-4 rounded-xl border-2 cursor-pointer ' +
        'transition-all duration-200 text-center ' +
        (selected
          ? 'border-brand-purple bg-brand-purple text-white shadow-lg'
          : 'border-purple-100 bg-white text-gray-700 hover:border-brand-purple-light hover:shadow-md')
      }
    >
      <input
        type="radio"
        name={name}
        value={value}
        checked={selected}
        onChange={onChange}
        className="sr-only"
      />
      <span className="text-lg">{description}</span>
      <span className="text-sm font-semibold">{label}</span>
    </label>
  )
}

async function saveOrderToFirestore(form) {
  if (!isFirebaseReady) {
    // Demo mode — simulate a Firestore document ID so the UI still works
    return `demo${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
  }
  const ref = await addDoc(collection(db, 'orders'), {
    fullName:               form.fullName,
    contactInfo:            form.contactInfo,
    perfumeType:            form.perfumeType,
    baseType:               form.baseType,
    scentNotes:             form.scentNotes,
    quantity:               Number(form.quantity),
    additionalInstructions: form.additionalInstructions,
    status:                 'pending',
    createdAt:              serverTimestamp(),
  })
  return ref.id
}

async function sendOwnerEmail(form, orderId) {
  // Skip silently if EmailJS is not configured yet
  if (!import.meta.env.VITE_EMAILJS_SERVICE_ID) return

  const orderRef = `#${orderId.substring(0, 8).toUpperCase()}`
  const orderDate = new Date().toLocaleString('en-NG', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })

  await emailjs.send(
    import.meta.env.VITE_EMAILJS_SERVICE_ID,
    import.meta.env.VITE_EMAILJS_TEMPLATE_ID,
    {
      order_id:      orderRef,
      customer_name: form.fullName,
      contact_info:  form.contactInfo,
      perfume_type:  form.perfumeType,
      base_type:     form.baseType,
      scent_notes:   form.scentNotes,
      quantity:      form.quantity,
      instructions:  form.additionalInstructions || 'None',
      order_date:    orderDate,
    },
    import.meta.env.VITE_EMAILJS_PUBLIC_KEY,
  )
}

function OrderForm({ onSuccess }) {
  const [form, setForm] = useState(INITIAL_FORM)
  const [errors, setErrors] = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')

  const validate = () => {
    const e = {}
    if (!form.fullName.trim())    e.fullName    = 'Please enter your full name'
    if (!form.contactInfo.trim()) e.contactInfo = 'Please enter your WhatsApp number or email'
    if (!form.perfumeType)        e.perfumeType = 'Please select a perfume type'
    if (!form.baseType)           e.baseType    = 'Please select a base type'
    if (!form.scentNotes.trim())  e.scentNotes  = 'Please describe your preferred scent or notes'
    if (!form.quantity || Number(form.quantity) < 1) e.quantity = 'Quantity must be at least 1'
    return e
  }

  const handleChange = (e) => {
    const { name, value } = e.target
    setForm(prev => ({ ...prev, [name]: value }))
    if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }))
    if (submitError)  setSubmitError('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const found = validate()
    if (Object.keys(found).length > 0) {
      setErrors(found)
      return
    }

    setIsSubmitting(true)
    setSubmitError('')

    try {
      // 1. Save order to Firestore
      const orderId = await saveOrderToFirestore(form)

      // 2. Notify owner by email (non-blocking — order succeeds even if email fails)
      sendOwnerEmail(form, orderId).catch((err) => {
        console.warn('Owner email notification failed:', err)
      })

      // 3. Show success screen
      onSuccess(form, orderId)

    } catch (err) {
      console.error('Order submission error:', err)
      setSubmitError(
        'We couldn\'t place your order right now. Please check your internet connection and try again, ' +
        'or contact us directly on WhatsApp.'
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-6">

      {/* Full Name */}
      <div>
        <Label htmlFor="fullName">Customer Full Name</Label>
        <input
          id="fullName"
          type="text"
          name="fullName"
          value={form.fullName}
          onChange={handleChange}
          placeholder="e.g. Amara Johnson"
          className={`${inputBase} ${errors.fullName ? inputError : inputValid}`}
        />
        <FieldError msg={errors.fullName} />
      </div>

      {/* Contact Info */}
      <div>
        <Label htmlFor="contactInfo">WhatsApp Number or Email</Label>
        <input
          id="contactInfo"
          type="text"
          name="contactInfo"
          value={form.contactInfo}
          onChange={handleChange}
          placeholder="e.g. +234 801 234 5678 or you@email.com"
          className={`${inputBase} ${errors.contactInfo ? inputError : inputValid}`}
        />
        <FieldError msg={errors.contactInfo} />
      </div>

      {/* Perfume Type */}
      <div>
        <Label>Perfume Type</Label>
        <div className="grid grid-cols-2 gap-3">
          <RadioCard name="perfumeType" value="Brand Perfume"
            selected={form.perfumeType === 'Brand Perfume'} onChange={handleChange}
            label="Brand Perfume" description="🏷️" />
          <RadioCard name="perfumeType" value="Custom Blend"
            selected={form.perfumeType === 'Custom Blend'} onChange={handleChange}
            label="Custom Blend" description="🌸" />
        </div>
        <FieldError msg={errors.perfumeType} />
      </div>

      {/* Base Type */}
      <div>
        <Label>Base Type</Label>
        <div className="grid grid-cols-2 gap-3">
          <RadioCard name="baseType" value="Oil Based"
            selected={form.baseType === 'Oil Based'} onChange={handleChange}
            label="Oil Based" description="💧" />
          <RadioCard name="baseType" value="Alcohol Based"
            selected={form.baseType === 'Alcohol Based'} onChange={handleChange}
            label="Alcohol Based" description="✨" />
        </div>
        <FieldError msg={errors.baseType} />
      </div>

      {/* Scent Notes */}
      <div>
        <Label htmlFor="scentNotes">Preferred Scent / Notes</Label>
        <textarea
          id="scentNotes"
          name="scentNotes"
          value={form.scentNotes}
          onChange={handleChange}
          placeholder="e.g. Floral with vanilla undertones, inspired by Chanel No. 5, woody musk base..."
          rows={3}
          className={`${inputBase} resize-none ${errors.scentNotes ? inputError : inputValid}`}
        />
        <FieldError msg={errors.scentNotes} />
      </div>

      {/* Quantity */}
      <div>
        <Label htmlFor="quantity">Quantity</Label>
        <input
          id="quantity"
          type="number"
          name="quantity"
          value={form.quantity}
          onChange={handleChange}
          min="1"
          max="100"
          className={`${inputBase} ${errors.quantity ? inputError : inputValid}`}
          style={{ maxWidth: '160px' }}
        />
        <FieldError msg={errors.quantity} />
      </div>

      {/* Additional Instructions */}
      <div>
        <Label htmlFor="additionalInstructions" optional>Additional Instructions</Label>
        <textarea
          id="additionalInstructions"
          name="additionalInstructions"
          value={form.additionalInstructions}
          onChange={handleChange}
          placeholder="Any special packaging, delivery notes, gift wrapping requests..."
          rows={3}
          className={`${inputBase} resize-none ${inputValid}`}
        />
      </div>

      {/* Submission error */}
      {submitError && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm flex gap-3">
          <span className="text-xl">⚠️</span>
          <span>{submitError}</span>
        </div>
      )}

      {/* Divider */}
      <div className="flex items-center gap-3 py-1">
        <div className="flex-1 h-px bg-purple-100" />
        <span className="text-brand-gold text-lg">✦</span>
        <div className="flex-1 h-px bg-purple-100" />
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={isSubmitting}
        className="w-full py-4 rounded-xl font-bold text-base tracking-widest uppercase shadow-lg transition-all duration-300 disabled:opacity-70 disabled:cursor-not-allowed flex items-center justify-center gap-2 cursor-pointer"
        style={{
          background: isSubmitting
            ? '#c9a030'
            : 'linear-gradient(135deg, #D4AF37 0%, #F0D060 50%, #D4AF37 100%)',
          color: '#1E0437',
          boxShadow: '0 4px 20px rgba(212, 175, 55, 0.4)',
        }}
      >
        {isSubmitting ? (
          <>
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Placing Order…
          </>
        ) : (
          <>✦ Place My Order ✦</>
        )}
      </button>

      <p className="text-center text-gray-400 text-xs">
        Fields marked with <span className="text-brand-gold font-bold">✦</span> are required
      </p>

      {!isFirebaseReady && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-center">
          <p className="text-amber-700 text-xs font-medium">
            🔧 Demo Mode — orders are not saved yet.
            Add your Firebase credentials in <code className="bg-amber-100 px-1 rounded">.env</code> to go live.
          </p>
        </div>
      )}
    </form>
  )
}

export default OrderForm
