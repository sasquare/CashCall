import { useState } from 'react'

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

function OrderForm({ onSuccess }) {
  const [form, setForm] = useState(INITIAL_FORM)
  const [errors, setErrors] = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)

  const validate = () => {
    const e = {}
    if (!form.fullName.trim())     e.fullName    = 'Please enter your full name'
    if (!form.contactInfo.trim())  e.contactInfo = 'Please enter your WhatsApp number or email'
    if (!form.perfumeType)         e.perfumeType = 'Please select a perfume type'
    if (!form.baseType)            e.baseType    = 'Please select a base type'
    if (!form.scentNotes.trim())   e.scentNotes  = 'Please describe your preferred scent or notes'
    if (!form.quantity || Number(form.quantity) < 1) e.quantity = 'Quantity must be at least 1'
    return e
  }

  const handleChange = (e) => {
    const { name, value } = e.target
    setForm(prev => ({ ...prev, [name]: value }))
    if (errors[name]) setErrors(prev => ({ ...prev, [name]: '' }))
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const found = validate()
    if (Object.keys(found).length > 0) {
      setErrors(found)
      const firstErrorField = document.querySelector('[data-error="true"]')
      firstErrorField?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      return
    }
    setIsSubmitting(true)
    setTimeout(() => {
      setIsSubmitting(false)
      onSuccess(form)
    }, 1400)
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-6">

      {/* Full Name */}
      <div data-error={!!errors.fullName}>
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
      <div data-error={!!errors.contactInfo}>
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
      <div data-error={!!errors.perfumeType}>
        <Label>Perfume Type</Label>
        <div className="grid grid-cols-2 gap-3">
          <RadioCard
            name="perfumeType"
            value="Brand Perfume"
            selected={form.perfumeType === 'Brand Perfume'}
            onChange={handleChange}
            label="Brand Perfume"
            description="🏷️"
          />
          <RadioCard
            name="perfumeType"
            value="Custom Blend"
            selected={form.perfumeType === 'Custom Blend'}
            onChange={handleChange}
            label="Custom Blend"
            description="🌸"
          />
        </div>
        <FieldError msg={errors.perfumeType} />
      </div>

      {/* Base Type */}
      <div data-error={!!errors.baseType}>
        <Label>Base Type</Label>
        <div className="grid grid-cols-2 gap-3">
          <RadioCard
            name="baseType"
            value="Oil Based"
            selected={form.baseType === 'Oil Based'}
            onChange={handleChange}
            label="Oil Based"
            description="💧"
          />
          <RadioCard
            name="baseType"
            value="Alcohol Based"
            selected={form.baseType === 'Alcohol Based'}
            onChange={handleChange}
            label="Alcohol Based"
            description="✨"
          />
        </div>
        <FieldError msg={errors.baseType} />
      </div>

      {/* Scent Notes */}
      <div data-error={!!errors.scentNotes}>
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
      <div data-error={!!errors.quantity}>
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
    </form>
  )
}

export default OrderForm
