import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    Timer {
        interval: 20000
        repeat: true
        onTriggered: presentation.goToNextSlide()
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            color: "#000000"
        }
        Image {
            id: logo
            source: "welcome.png"
            width: 360
            height: 270
            fillMode: Image.PreserveAspectFit
            anchors.centerIn: parent
        }
        Text {
            anchors.horizontalCenter: logo.horizontalCenter
            anchors.top: logo.bottom
            anchors.topMargin: 16
            color: "#FFFFFF"
            text: qsTr("Welcome to VPinOS.<br/>"+
                  "The rest of the installation is automated and should complete in a few minutes.")
            wrapMode: Text.WordWrap
            width: 600
            horizontalAlignment: Text.Center
        }
    }
}
