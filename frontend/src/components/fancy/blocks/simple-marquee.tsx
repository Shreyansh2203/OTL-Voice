import React, { useRef, useState, useEffect } from "react";
import { motion, animate, useMotionValue } from "motion/react";

interface SimpleMarqueeProps {
  children: React.ReactNode;
  className?: string;
  direction?: "up" | "down" | "left" | "right";
  baseVelocity?: number;
  repeat?: number;
  easing?: (x: number) => number;
}

export default function SimpleMarquee({
  children,
  className = "",
  direction = "left",
  baseVelocity = 50,
  repeat = 4,
  easing
}: SimpleMarqueeProps) {
  const [contentSize, setContentSize] = useState(0);
  const contentRef = useRef<HTMLDivElement>(null);
  
  const isVertical = direction === "up" || direction === "down";
  const factor = direction === "down" || direction === "right" ? 1 : -1;
  
  const position = useMotionValue(0);

  useEffect(() => {
    if (!contentRef.current) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        setContentSize(isVertical ? entry.contentRect.height : entry.contentRect.width);
      }
    });
    observer.observe(contentRef.current);
    return () => observer.disconnect();
  }, [isVertical]);

  useEffect(() => {
    if (contentSize > 0) {
      // The start position and end position depend on the direction.
      // If factor is -1 (up, left), it moves from 0 to -contentSize.
      // If factor is 1 (down, right), it needs to move from -contentSize to 0, or 0 to contentSize.
      // To keep it smooth, let's just animate from 0 to factor * contentSize
      // Wait, if it moves from 0 to contentSize (factor=1), it means it moves down.
      // When it hits contentSize, it snaps back to 0. But to prevent flashing, we need the copies.
      
      let from = 0;
      let to = factor * contentSize;

      if (factor === 1) {
        // If it's moving down/right, we want to animate from -contentSize to 0 to make it infinite
        from = -contentSize;
        to = 0;
      }

      position.set(from);

      const controls = animate(position, [from, to], {
        ease: easing || "linear",
        duration: contentSize / baseVelocity,
        repeat: Infinity,
        repeatType: "loop"
      });
      return controls.stop;
    }
  }, [contentSize, baseVelocity, factor, position, easing]);

  const transformKey = isVertical ? "y" : "x";

  // For down/right movement (factor = 1), we need an extra copy at the start 
  // or we need to offset the whole container to hide the snap.
  // Actually, if we just render N copies, when it animates from -contentSize to 0,
  // we start looking at the -contentSize offset (which means it's pulled up by 1 copy),
  // and it moves to 0. This works perfectly as long as we have enough copies.

  return (
    <div style={{ overflow: "hidden", display: "flex", flexDirection: isVertical ? "column" : "row" }} className={className}>
      <motion.div
        style={{
          display: "flex",
          flexDirection: isVertical ? "column" : "row",
          [transformKey]: position
        }}
      >
        {Array.from({ length: repeat }).map((_, i) => (
          <div 
            key={i} 
            ref={i === 0 ? contentRef : null} 
            style={{ display: "flex", flexDirection: isVertical ? "column" : "row", flexShrink: 0 }}
          >
            {children}
          </div>
        ))}
      </motion.div>
    </div>
  );
}
