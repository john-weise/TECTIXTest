// src/components/admin/AboutPanel.tsx
import React from "react";

/** AboutPanel — static content for the admin area */
const TECTIX_VERSION = "2.3.0";

export default function AboutPanel() {
  return (
    <>
      <div
        className="about-header"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
        }}
      >
        <h2 className="section-title">About TECTIX</h2>
        <span
          className="version-pill"
          style={{
            marginLeft: "auto",
            padding: "0.15rem 0.9rem",
            borderRadius: "9999px",
            backgroundColor: "#ea580c", // orange pill
            color: "#ffffff",
            fontWeight: 600,
            fontFamily: "monospace",
            fontSize: "0.9rem",
          }}
        >
          {`v${TECTIX_VERSION}`}
        </span>
      </div>

      <div className="gold-rule" aria-hidden="true" />

      {/* Oregon Trail Time! Saddle Up!! */}
      <div
        className="tectix-terminal"
        style={{
          marginTop: "1rem",
          color: "#00ff66",
          fontFamily:
            '"SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
        }}
      >
        <div
          className="tectix-terminal-inner"
          style={{
            backgroundColor: "#000000",
            padding: "2rem 2.5rem", // bigger window
            borderRadius: "0.5rem",
            overflowX: "auto",
          }}
        >
          <pre
            aria-label="TECTIX ASCII logo and credits"
            style={{
              margin: 0,
              whiteSpace: "pre",
              lineHeight: 1.2,
              fontSize: "1.25rem", // ~2x typical monospace size
            }}
          >{String.raw`
           #####                                                          
          #######                                                         
 **       #######                                                         
***********##### *******                                                  
 ***********************                                                  
       ===************                                                    
    ======== ****     **********    *           *********  ****       ****
   ====        ***   ************ ****        ************  *****   ***** 
 ===            **   ***      ********        ****           **********   
==              **   *****************        ***********      *******    
               **    ************ ****        ****            *********   
              *      ***          *********** ************  *****  ****** 
                     ***          *********** ***********  *****     *****
                                                                              
TECTIX Version ${TECTIX_VERSION}
PLEX SOLUTIONS, LLC
JOHN WEISE, RICHARD TRAPP, LOGAN LOYACK`}
          </pre>
        </div>
      </div>
    </>
  );
}

